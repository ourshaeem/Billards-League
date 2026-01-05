CREATE DATABASE IF NOT EXISTS ranked_billards;
CREATE DATABASE ranked_billards;
use ranked_billards;


-- 1. RANKS
CREATE TABLE Ranks (
    rank_id INT AUTO_INCREMENT PRIMARY KEY,
    rank_name VARCHAR(50) NOT NULL UNIQUE, --  'Bronze', 'Gold'
    min_elo INT NOT NULL,                  --  1000, 1500
    icon_url VARCHAR(255)                  -- Link to rank badge image
);

-- 2. PLAYERS (The core user table)
CREATE TABLE Players (
    user_id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    bio TEXT,                              -- The "About Me" section
    elo_rating INT DEFAULT 0,           -- Starting Score
    total_wins INT DEFAULT 0,
    total_losses INT DEFAULT 0,
    rank_id INT,                           -- Links to Ranks table
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (rank_id) REFERENCES Ranks(rank_id)
);

-- 3. LEAGUES (The groups)
CREATE TABLE Leagues (
    league_id INT AUTO_INCREMENT PRIMARY KEY,
    league_name VARCHAR(255) NOT NULL,
    league_record_streak INT DEFAULT 0,
    is_private BOOL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. LEAGUE_MEMBERS (Who belongs to which group)
CREATE TABLE League_Members (
    league_id INT,
    user_id INT,
    role ENUM('Member', 'Admin', 'Owner') DEFAULT 'Member', -- Smart Roles
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (league_id, user_id),      -- Prevents duplicate joining
    FOREIGN KEY (league_id) REFERENCES Leagues(league_id),
    FOREIGN KEY (user_id) REFERENCES Players(user_id)
);

-- 5. POOL_TABLES (The physical locations)
CREATE TABLE Pool_Tables (
    table_id INT AUTO_INCREMENT PRIMARY KEY,
    league_id INT,
    table_name VARCHAR(50) NOT NULL,       --  'Blue Table' etc
    current_king_id INT,                   -- Who currently owns the table
    match_code INT,                        -- The secret code to join
    current_streak INT DEFAULT 0,
    table_record_streak INT DEFAULT 0,
    FOREIGN KEY (league_id) REFERENCES Leagues(league_id),
    FOREIGN KEY (current_king_id) REFERENCES Players(user_id)
);

-- 6. QUEUE (The waiting line)
CREATE TABLE Queue (
    queue_id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT,
    table_id INT,
    queue_position INT NOT NULL,
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES Players(user_id),
    FOREIGN KEY (table_id) REFERENCES Pool_Tables(table_id)
);

-- 7. MATCHES (The history/receipts)
CREATE TABLE Matches (
    match_id INT AUTO_INCREMENT PRIMARY KEY,
    table_id INT,
    king_id INT,
    challenger_id INT,
    winner_id INT,
    loser_id INT,                          -- Added for easy ELO math
    king_balls INT,
    challenger_balls INT,                 
    elo_change INT,                        -- The points swapped
    match_status ENUM('Upcoming', 'Active', 'Finished') DEFAULT 'Upcoming',
    played_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (table_id) REFERENCES Pool_Tables(table_id),
    FOREIGN KEY (king_id) REFERENCES Players(user_id),
    FOREIGN KEY (challenger_id) REFERENCES Players(user_id),
    FOREIGN KEY (winner_id) REFERENCES Players(user_id),
    FOREIGN KEY (loser_id) REFERENCES Players(user_id)
);