"""
Voting off an absent king.

What it's for: a king who walked off holds the table for nobody. Everyone
waiting who could play there - and the challenger already seated against
them - votes; when all of them have, the king has a minute to say they're
here, and then matchmaking takes them off: the table goes to the next in
line, or, mid-game, the game is called off with nothing recorded and the
challenger holds the table.
"""
import unittest

from tests.conftest_base import ApiTestCase
from models import BILLIARDS, KingVote, Match, PoolTable, db

from logic.king_votes import (
    HERE_RESULT_CLEARED,
    VOTE_GRACE_SECONDS,
    VOTE_RESULT_ALREADY_VOTED,
    VOTE_RESULT_EVERYONE_VOTED,
    VOTE_RESULT_VOTED,
    VOTE_RESULT_WITHDRAWN,
    cast_vote,
    king_is_here,
    summary,
)
from logic.manage_queue import RECENTLY_HERE_SECONDS, attempt_matchmaking, join_queue
from logic.record_match import record_match_result
from logic.tables import table_snapshot

A_WHILE = RECENTLY_HERE_SECONDS + 240


class KingVoteTestCase(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.dave = self.add_player("dave")

    def wait(self, user_id, table_id=None):
        """In the queue, long enough ago to be asked when their turn comes."""
        join_queue(user_id, BILLIARDS, table_id)
        self.backdate_queue_join(user_id, A_WHILE)

    def match(self, table_id=1):
        db.session.expire_all()
        return self.active_match(table_id)

    def vote(self, user_id, remove=True, table_id=1):
        return cast_vote(user_id, table_id, None, remove)[0]

    def minute_passes(self, table_id=1):
        match = self.match(table_id)
        db.session.execute(
            db.text("UPDATE Matches SET removal_vote_at = datetime('now', :offset) WHERE match_id = :id"),
            {"offset": f"-{VOTE_GRACE_SECONDS + 1} seconds", "id": match.match_id},
        )
        db.session.commit()
        db.session.expire_all()

    def king_waiting_with_two_in_line(self):
        """alice holds Table 1; bob is up (not yet confirmed), carol behind him."""
        self.make_king(self.alice)
        self.wait(self.bob)
        self.wait(self.carol)
        attempt_matchmaking(BILLIARDS)


class EveryoneHasToVote(KingVoteTestCase):
    def test_one_vote_isnt_enough(self):
        self.king_waiting_with_two_in_line()

        self.assertEqual(self.vote(self.bob), VOTE_RESULT_VOTED)

        vote = summary(self.match())
        self.assertEqual((vote["votes"], vote["needed"], vote["seconds_left"]), (1, 2, None))
        self.assertIsNone(self.match().removal_vote_at)

    def test_when_everyone_has_the_king_gets_a_minute(self):
        self.king_waiting_with_two_in_line()
        self.vote(self.bob)

        self.assertEqual(self.vote(self.carol), VOTE_RESULT_EVERYONE_VOTED)

        self.assertEqual(summary(self.match())["seconds_left"], VOTE_GRACE_SECONDS)
        attempt_matchmaking(BILLIARDS)
        self.assertEqual(self.match().player_one_id, self.alice, "still theirs inside the minute")

    def test_voting_twice_counts_once(self):
        self.king_waiting_with_two_in_line()
        self.vote(self.bob)

        self.assertEqual(self.vote(self.bob), VOTE_RESULT_ALREADY_VOTED)
        self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(KingVote)), 1)

    def test_taking_a_vote_back_stops_the_minute(self):
        self.king_waiting_with_two_in_line()
        self.vote(self.bob)
        self.vote(self.carol)

        self.assertEqual(self.vote(self.carol, remove=False), VOTE_RESULT_WITHDRAWN)

        self.assertIsNone(self.match().removal_vote_at)
        self.assertEqual(summary(self.match())["votes"], 1)

    def test_joining_after_everyone_voted_doesnt_stop_it(self):
        self.king_waiting_with_two_in_line()
        self.vote(self.bob)
        self.vote(self.carol)

        self.wait(self.dave)
        self.minute_passes()
        attempt_matchmaking(BILLIARDS)

        self.assertNotEqual(getattr(self.match(), "player_one_id", None), self.alice)

    def test_someone_who_hadnt_voted_leaving_completes_it(self):
        self.king_waiting_with_two_in_line()
        self.vote(self.bob)
        from logic.manage_queue import leave_queue

        leave_queue(self.carol, BILLIARDS)
        attempt_matchmaking(BILLIARDS)

        self.assertIsNotNone(self.match().removal_vote_at)


class WhoVotes(KingVoteTestCase):
    def test_those_waiting_for_another_table_dont(self):
        db.session.add(PoolTable(table_id=3, table_name="Table 2", league_id=self.billiards_league_id, league_type=BILLIARDS))
        db.session.commit()
        self.start_match(self.add_player("x"), self.add_player("y"), table_id=3)
        self.king_waiting_with_two_in_line()
        self.wait(self.dave, 3)

        vote = summary(self.match())

        self.assertEqual(vote["electorate"], [self.bob, self.carol])

    def test_the_challenger_seated_against_the_king_does(self):
        self.start_match(self.alice, self.bob)
        self.wait(self.carol)

        self.assertEqual(summary(self.match())["electorate"], [self.bob, self.carol])

    def test_with_nobody_waiting_theres_no_vote(self):
        self.make_king(self.alice)

        self.assertIsNone(summary(self.match()))


class TheKingComesOff(KingVoteTestCase):
    def test_a_king_alone_gives_the_table_to_the_next_two(self):
        self.king_waiting_with_two_in_line()
        self.vote(self.bob)
        self.vote(self.carol)

        self.minute_passes()
        attempt_matchmaking(BILLIARDS)

        self.assertIsNone(self.match(), "the king's row is gone; bob and carol are asked")
        bob, carol = self.queued(self.bob), self.queued(self.carol)
        self.assertTrue(bob.is_called and carol.is_called)
        self.assertEqual((bob.table_id, carol.table_id), (1, 1))
        self.login_as(self.alice)
        self.assertEqual(self.get("/match/status").get_json()["status"], "idle")

    def test_mid_game_its_called_off_and_the_challenger_holds_the_table(self):
        self.start_match(self.alice, self.bob)
        ratings = (self.rating(self.alice), self.rating(self.bob))
        self.vote(self.bob)  # nobody else waiting: bob is everyone

        self.minute_passes()
        self.login_as(self.bob)
        body = self.get("/match/status").get_json()  # bob's own poll is enough

        self.assertEqual(body["status"], "waiting_for_challenger")
        self.assertEqual(self.match().player_one_id, self.bob)
        self.assertEqual((self.rating(self.alice), self.rating(self.bob)), ratings, "nothing recorded")
        finished = db.session.scalar(
            db.select(db.func.count()).select_from(Match).where(Match.match_status == Match.STATUS_FINISHED)
        )
        self.assertEqual(finished, 0)
        self.assertEqual(db.session.scalar(db.select(db.func.count()).select_from(KingVote)), 0)

    def test_the_king_saying_theyre_here_clears_every_vote(self):
        self.king_waiting_with_two_in_line()
        self.vote(self.bob)
        self.vote(self.carol)

        self.assertEqual(king_is_here(self.alice), HERE_RESULT_CLEARED)

        self.assertEqual(summary(self.match())["votes"], 0)
        self.assertIsNone(self.match().removal_vote_at)
        attempt_matchmaking(BILLIARDS)
        self.assertEqual(self.match().player_one_id, self.alice)

    def test_votes_are_for_this_reign_only(self):
        self.start_match(self.alice, self.bob)
        self.wait(self.carol)
        self.vote(self.carol)

        record_match_result(self.match(), self.alice, self.bob, 16)

        self.assertEqual(summary(self.match())["votes"], 0, "a new reign starts with no votes")

    def queued(self, user_id):
        from models import QueueEntry

        db.session.expire_all()
        return db.session.scalars(db.select(QueueEntry).where(QueueEntry.user_id == user_id)).first()


class VoteRoutes(KingVoteTestCase):
    def post_vote(self, user_id, **body):
        self.login_as(user_id)
        return self.post("/table/vote", json={"table_id": 1, **body})

    def test_voting_and_where_it_stands(self):
        self.king_waiting_with_two_in_line()

        res = self.post_vote(self.bob, match_id=self.match().match_id)

        self.assertEqual(res.status_code, 200)
        body = res.get_json()
        self.assertEqual(body["status"], VOTE_RESULT_VOTED)
        self.assertIn("1 of 2", body["message"])
        self.assertEqual(body["removal_vote"]["voters"], [self.bob])

        res = self.post_vote(self.carol)
        self.assertEqual(res.get_json()["status"], VOTE_RESULT_EVERYONE_VOTED)
        self.assertIn("has a minute to say they're here", res.get_json()["message"])

    def test_the_table_shows_the_vote(self):
        self.king_waiting_with_two_in_line()
        self.post_vote(self.bob)

        vote = self.client.get("/table/1").get_json()["table"]["removal_vote"]

        self.assertEqual(
            vote,
            {"votes": 1, "needed": 2, "voters": [self.bob], "electorate": [self.bob, self.carol], "seconds_left": None},
        )

    def test_the_king_sees_it_and_can_say_theyre_here(self):
        self.king_waiting_with_two_in_line()
        self.post_vote(self.bob)
        self.post_vote(self.carol)

        self.login_as(self.alice)
        vote = self.get("/match/status").get_json()["removal_vote"]
        self.assertEqual((vote["votes"], vote["needed"], vote["you_can_vote"]), (2, 2, False))
        self.assertIsNotNone(vote["seconds_left"])

        res = self.post("/table/here")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()["status"], HERE_RESULT_CLEARED)

    def test_the_challenger_can_vote_from_their_game(self):
        self.start_match(self.alice, self.bob)
        self.login_as(self.bob)

        vote = self.get("/match/status").get_json()["removal_vote"]

        self.assertEqual((vote["you_can_vote"], vote["you_voted"], vote["needed"]), (True, False, 1))

    def test_refusals(self):
        self.king_waiting_with_two_in_line()
        old = self.match().match_id

        self.assertEqual(self.post_vote(self.alice).status_code, 409, "not on yourself")
        self.assertEqual(self.post_vote(self.dave).status_code, 403, "not waiting here")
        self.assertEqual(self.post_vote(self.bob, match_id=old + 99).status_code, 409, "the table changed hands")
        self.login_as(self.bob)
        self.assertEqual(self.post("/table/vote", json={}).status_code, 400)
        self.assertEqual(self.post("/table/vote", json={"table_id": 1, "remove": "yes"}).status_code, 400)
        self.login_as(self.bob)
        self.assertEqual(self.post("/table/here").status_code, 404, "only a king is here or not")

    def test_no_king_no_vote(self):
        self.wait(self.bob)

        self.assertEqual(self.post_vote(self.bob).status_code, 404)

    def test_needs_a_login(self):
        self.assertEqual(self.client.post("/table/vote", json={"table_id": 1}).status_code, 401)


if __name__ == "__main__":
    unittest.main()
