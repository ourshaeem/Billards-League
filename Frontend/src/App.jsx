import React, { useState, useEffect } from 'react';
import { Trophy, Users, LogIn, PlayCircle, ArrowRight, AlertCircle, Swords } from 'lucide-react';

const API_BASE = "http://localhost:5000";

function App() {
  const [view, setView] = useState('login'); 
  const [leaderboard, setLeaderboard] = useState([]);
  const [queue, setQueue] = useState([]);
  const [user, setUser] = useState(null); 
  const [matchStatus, setMatchStatus] = useState({ status: 'idle' });
  const [loading, setLoading] = useState(false);
  const [matchmakingStatus, setMatchmakingStatus] = useState('');

  // --- 1. DATA FETCHING ---
  const fetchData = async () => {
    try {
      // 1. Public Data
      const [lbRes, qRes] = await Promise.all([
        fetch(`${API_BASE}/leaderboard`),
        fetch(`${API_BASE}/queue/1`)
      ]);

      if (lbRes.ok) setLeaderboard(await lbRes.json());
      if (qRes.ok) setQueue(await qRes.json());

      // 2. Protected Data (Status) - Only if user is logged in
      if (user) {
        const token = localStorage.getItem('token');
        if (token) {
          const sRes = await fetch(`${API_BASE}/match/status`, { 
            headers: { 'Authorization': `Bearer ${token}` }
          });

          if (sRes.ok) {
            const data = await sRes.json();
            console.log("Match status data:", data); // Debug
            setMatchStatus(data);
            
            // Update matchmaking status
            if (data.status === 'playing') {
              setMatchmakingStatus(`Match started! You're playing against ${data.opponent}`);
            } else if (queue.length >= 2) {
              setMatchmakingStatus('Match ready! Waiting for system to create match...');
            } else if (queue.length === 1) {
              setMatchmakingStatus('Waiting for 1 more player to start match...');
            } else {
              setMatchmakingStatus('Join queue to start a match');
            }
          } else if (sRes.status === 401) {
            console.log("Token expired");
            handleLogout();
          }
        }
      }
    } catch (err) {
      console.error("Fetch error:", err);
    }
  };

  useEffect(() => {
    fetchData();
    const interval = setInterval(() => {
      if (user) fetchData(); 
    }, 2000); // Poll every 2 seconds for faster updates
    
    return () => clearInterval(interval);
  }, [user, queue.length]);

  // --- 2. ACTIONS ---
  const handleRegister = async (e) => {
    e.preventDefault();
    setLoading(true);
    
    const formData = {
      username: e.target.username.value,
      first_name: e.target.firstname.value,
      last_name: e.target.lastname.value,
      password: e.target.password.value
    };

    try {
      const res = await fetch(`${API_BASE}/register`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData)
      });

      if (res.ok) {
        alert("Registration successful! Please login.");
        setView('login');
      } else {
        alert("Registration failed. Username might be taken.");
      }
    } catch (error) {
      alert("Network error. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleLogin = async (e) => {
    e.preventDefault();
    setLoading(true);
    
    const username = e.target.username.value;
    const password = e.target.password.value;

    try {
      const res = await fetch(`${API_BASE}/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });

      if (res.ok) {
        const data = await res.json();
        // Store the token and user info
        localStorage.setItem('token', data.access_token);
        localStorage.setItem('user_id', data.user_id);
        localStorage.setItem('username', data.username);
        
        setUser({ 
          user_id: data.user_id, 
          username: data.username 
        });
        setView('dashboard'); // Go directly to dashboard
      } else {
        alert("Login Failed: Check username/password");
      }
    } catch (error) {
      alert("Network error. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleJoinQueue = async () => {
    const token = localStorage.getItem('token');
    if (!token) {
      alert("Please login first");
      setView('login');
      return;
    }

    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/queue/join`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ table_id: 1 })
      });

      if (res.ok) {
        const data = await res.json();
        alert(data.message);
        fetchData();
        
        // If match was created, show message
        if (data.message.includes("match started")) {
          setMatchmakingStatus("Match created! Check your status above.");
        }
      } else {
        const err = await res.json();
        alert("Error: " + err.message);
      }
    } catch (error) {
      alert("Network error. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleRecordMatch = async (myBalls, oppBalls) => {
    const token = localStorage.getItem('token');
    if (!token) return;

    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/match/record`, {
        method: 'POST',
        headers: { 
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ 
          my_balls: parseInt(myBalls), 
          opp_balls: parseInt(oppBalls) 
        })
      });

      if (res.ok) {
        const data = await res.json();
        alert(`Match recorded! ELO change: ${data.elo_change}`);
        fetchData();
      } else {
        const err = await res.json();
        alert("Error: " + err.message);
      }
    } catch (error) {
      alert("Network error. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('user_id');
    localStorage.removeItem('username');
    setUser(null);
    setMatchStatus({ status: 'idle' });
    setView('login');
  };

  const forceStartMatch = async () => {
    // Debug function to force match start
    try {
      const res = await fetch(`${API_BASE}/debug/start-match`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ table_id: 1 })
      });
      
      if (res.ok) {
        const data = await res.json();
        alert(`Match forced: ${data.player1} vs ${data.player2}`);
        fetchData();
      } else {
        alert("Could not force match");
      }
    } catch (error) {
      alert("Debug endpoint error");
    }
  };

  // --- 3. RENDER ---
  return (
    <div style={{ 
      padding: '20px', 
      backgroundColor: '#000301', 
      width: '100%', 
      minHeight: '100vh', 
      color: 'white', 
      fontFamily: 'Segoe UI, sans-serif' 
    }}>
      
      <h1 style={{textAlign: 'center', marginBottom: '10px'}}>🎱 Billiards League</h1>
      <p style={{textAlign: 'center', color: '#aaa', marginBottom: '30px'}}>
        Real-time matchmaking & leaderboard
      </p>

      {loading && (
        <div style={{
          position: 'fixed',
          top: '20px',
          right: '20px',
          background: '#0277bd',
          color: 'white',
          padding: '10px 20px',
          borderRadius: '5px',
          zIndex: 1000
        }}>
          Loading...
        </div>
      )}

      {view === 'login' && (
        <div style={authCardStyle}>
          <h2 style={authHeaderStyle}><LogIn size={24}/> Login</h2>
          <form onSubmit={handleLogin}>
            <input name="username" placeholder="Username" required style={inputStyle} />
            <input name="password" type="password" placeholder="Password" required style={inputStyle} />
            <button type="submit" style={btnPrimaryStyle} disabled={loading}>
              {loading ? 'Logging in...' : 'Enter League'}
            </button>
          </form>
          <button onClick={() => setView('register')} style={linkBtnStyle}>
            Don't have an account? Register here
          </button>
        </div>
      )}

      {view === 'register' && (
        <div style={authCardStyle}>
          <h2 style={authHeaderStyle}><Users size={24}/> Join the League</h2>
          <form onSubmit={handleRegister}>
            <input name="firstname" placeholder="First Name" required style={inputStyle} />
            <input name="lastname" placeholder="Last Name" required style={inputStyle} />
            <input name="username" placeholder="Choose Username" required style={inputStyle} />
            <input name="password" type="password" placeholder="Create Password" required style={inputStyle} />
            <button type="submit" style={{...btnPrimaryStyle, backgroundColor: '#2e7d32'}} disabled={loading}>
              {loading ? 'Creating Account...' : 'Create Account'}
            </button>
          </form>
          <button onClick={() => setView('login')} style={linkBtnStyle}>
            Already have an account? Login
          </button>
        </div>
      )}

      {view === 'dashboard' && user && (
        <div style={{ maxWidth: '1200px', margin: '0 auto' }}>
          {/* Header */}
          <div style={{ 
            display: 'flex', 
            justifyContent: 'space-between', 
            alignItems: 'center', 
            marginBottom: '20px',
            flexWrap: 'wrap',
            gap: '10px',
            padding: '15px',
            background: 'rgba(255,255,255,0.1)',
            borderRadius: '10px'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '15px' }}>
              <div style={{ 
                padding: '8px 16px', 
                background: matchStatus.status === 'playing' ? '#ff9800' : '#4caf50',
                borderRadius: '20px',
                fontWeight: 'bold',
                display: 'flex',
                alignItems: 'center',
                gap: '8px'
              }}>
                {matchStatus.status === 'playing' ? <Swords size={16} /> : <Users size={16} />}
                {matchStatus.status === 'playing' ? 'IN MATCH' : 'IDLE'}
              </div>
              <div>
                <div>Logged in as: <strong>{user?.username}</strong></div>
                <div style={{ fontSize: '0.9em', color: '#aaa' }}>User ID: {user?.user_id}</div>
              </div>
            </div>
            
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              {process.env.NODE_ENV === 'development' && (
                <button 
                  onClick={forceStartMatch}
                  style={{ 
                    background: '#9c27b0', 
                    border: 'none', 
                    color: '#fff', 
                    padding: '8px 16px', 
                    borderRadius: '4px', 
                    cursor: 'pointer',
                    fontSize: '0.9em'
                  }}
                >
                  Debug: Force Match
                </button>
              )}
              <button onClick={handleLogout} style={logoutBtnStyle}>
                Logout
              </button>
            </div>
          </div>
          
          {/* Matchmaking Status Banner */}
          {matchmakingStatus && (
            <div style={{
              padding: '15px',
              marginBottom: '20px',
              background: matchStatus.status === 'playing' ? 'rgba(255, 152, 0, 0.2)' : 'rgba(33, 150, 243, 0.2)',
              border: `1px solid ${matchStatus.status === 'playing' ? '#ff9800' : '#2196f3'}`,
              borderRadius: '8px',
              textAlign: 'center',
              fontWeight: 'bold'
            }}>
              {matchmakingStatus}
            </div>
          )}
          
          {/* Dashboard Grid */}
          <div style={{ 
            display: 'grid', 
            gridTemplateColumns: 'repeat(auto-fit, minmax(350px, 1fr))', 
            gap: '20px',
            marginBottom: '20px'
          }}>
            
            {/* STATUS/ACTION CARD */}
            <div style={cardStyle}>
              <h2 style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <PlayCircle size={24} />
                Your Status
              </h2>
              
              {matchStatus.status === 'playing' ? (
                <MatchReportingCard 
                  matchStatus={matchStatus}
                  onRecordMatch={handleRecordMatch}
                  disabled={loading}
                />
              ) : (
                <div style={{ textAlign: 'center', padding: '20px 0' }}>
                  <div style={{ fontSize: '3em', marginBottom: '20px' }}>🎱</div>
                  <p style={{ marginBottom: '20px', fontSize: '1.1em' }}>You are currently idle.</p>
                  <button 
                    onClick={handleJoinQueue} 
                    style={{...btnPrimaryStyle, padding: '15px', fontSize: '1.1em'}}
                    disabled={loading}
                  >
                    {loading ? 'Joining...' : 'Join Table 1 Queue'}
                  </button>
                  <div style={{ marginTop: '20px', fontSize: '0.9em', color: '#666' }}>
                    <AlertCircle size={16} style={{ verticalAlign: 'middle', marginRight: '5px' }} />
                    Queue length: {queue.length} player{queue.length !== 1 ? 's' : ''}
                  </div>
                </div>
              )}
            </div>

            {/* QUEUE CARD */}
            <div style={cardStyle}>
              <h2 style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <Users size={20}/> 
                Queue for Table 1
                <span style={{
                  background: queue.length >= 2 ? '#4caf50' : '#ff9800',
                  color: 'white',
                  padding: '2px 8px',
                  borderRadius: '12px',
                  fontSize: '0.7em'
                }}>
                  {queue.length} in queue
                </span>
              </h2>
              
              <div style={{ marginBottom: '15px', padding: '10px', background: '#f5f5f5', borderRadius: '6px' }}>
                <div style={{ fontSize: '0.9em', color: '#666', marginBottom: '5px' }}>Matchmaking Rules:</div>
                <div style={{ fontSize: '0.8em', color: '#888' }}>
                  • First 2 players in queue auto-matched<br/>
                  • Winner stays as "king" for next match<br/>
                  • Loser goes to back of queue<br/>
                  • ELO ratings updated after each match
                </div>
              </div>
              
              {queue.length === 0 ? (
                <p style={{color:'#888', textAlign: 'center', padding: '20px 0'}}>Queue is empty. Be the first to join!</p>
              ) : (
                <div style={{ maxHeight: '300px', overflowY: 'auto' }}>
                  {queue.map((q, idx) => ( 
                    <div key={q.user_id || idx} style={{ 
                      padding: '12px', 
                      borderBottom: '1px solid #eee', 
                      display: 'flex', 
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      background: idx < 2 ? '#fff8e1' : 'white'
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        <div style={{ 
                          background: idx < 2 ? '#ff9800' : '#4caf50', 
                          color: 'white',
                          width: '30px',
                          height: '30px',
                          borderRadius: '50%',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontWeight: 'bold'
                        }}>
                          {idx + 1}
                        </div>
                        <div>
                          <strong>{q.username}</strong>
                          {user?.username === q.username && (
                            <span style={{
                              marginLeft: '10px',
                              background: '#0277bd',
                              color: 'white',
                              padding: '2px 8px',
                              borderRadius: '10px',
                              fontSize: '0.8em'
                            }}>
                              YOU
                            </span>
                          )}
                        </div>
                      </div>
                      {idx < 2 && (
                        <span style={{ 
                          fontSize: '0.8em', 
                          color: '#ff9800',
                          fontWeight: 'bold',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '5px'
                        }}>
                          <Swords size={12} />
                          NEXT UP
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* LEADERBOARD CARD */}
          <div style={{ ...cardStyle }}>
            <h2 style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <Trophy size={20} color="#ff9800"/> 
              Live Leaderboard (Updates every 2s)
            </h2>
            {leaderboard.length === 0 ? (
              <p style={{color:'#888', textAlign: 'center', padding: '20px 0'}}>Loading leaderboard...</p>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: '600px' }}>
                  <thead>
                    <tr style={{borderBottom:'2px solid #eee', background: '#f5f5f5'}}>
                      <th style={{padding:'12px', textAlign:'left', width: '60px'}}>Rank</th>
                      <th style={{padding:'12px', textAlign:'left'}}>Player</th>
                      <th style={{padding:'12px', textAlign:'left', width: '100px'}}>ELO</th>
                      <th style={{padding:'12px', textAlign:'left', width: '100px'}}>W-L</th>
                      <th style={{padding:'12px', textAlign:'left', width: '80px'}}>Win %</th>
                    </tr>
                  </thead>
                  <tbody>
                    {leaderboard.map((p, idx) => {
                      const totalGames = p.total_wins + p.total_losses;
                      const winPercentage = totalGames > 0 ? ((p.total_wins / totalGames) * 100).toFixed(1) : '0.0';
                      
                      const isCurrentUser = user?.username === p.username;
                      
                      return (
                        <tr key={p.username} style={{
                          borderBottom: '1px solid #f0f0f0',
                          background: isCurrentUser ? '#e3f2fd' : (idx < 3 ? '#fff8e1' : 'white'),
                          fontWeight: isCurrentUser ? 'bold' : 'normal'
                        }}>
                          <td style={{padding:'12px'}}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                              #{idx + 1}
                              {idx < 3 && ['🥇', '🥈', '🥉'][idx]}
                            </div>
                          </td>
                          <td style={{padding:'12px'}}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                              {p.username}
                              {isCurrentUser && (
                                <span style={{
                                  background: '#0277bd',
                                  color: 'white',
                                  padding: '2px 8px',
                                  borderRadius: '10px',
                                  fontSize: '0.8em'
                                }}>
                                  YOU
                                </span>
                              )}
                            </div>
                            <div style={{ fontSize: '0.8em', color: '#666' }}>{p.rank_name || 'Unranked'}</div>
                          </td>
                          <td style={{padding:'12px', fontWeight: 'bold', color: '#2e7d32'}}>{p.elo_rating}</td>
                          <td style={{padding:'12px'}}>
                            <span style={{color: '#4caf50'}}>{p.total_wins}</span>
                            {' - '}
                            <span style={{color: '#f44336'}}>{p.total_losses}</span>
                          </td>
                          <td style={{padding:'12px'}}>{winPercentage}%</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// Match Reporting Component
function MatchReportingCard({ matchStatus, onRecordMatch, disabled }) {
  const [myBalls, setMyBalls] = useState('');
  const [oppBalls, setOppBalls] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!myBalls || !oppBalls) {
      alert("Please enter both scores");
      return;
    }
    if (parseInt(myBalls) === parseInt(oppBalls)) {
      alert("Scores cannot be equal");
      return;
    }
    onRecordMatch(myBalls, oppBalls);
  };

  return (
    <div style={{ backgroundColor: '#fff3e0', padding: '25px', borderRadius: '10px', border: '2px solid #ff9800', color: '#333' }}>
      <div style={{textAlign: 'center', marginBottom: '20px'}}>
        <div style={{ fontSize: '3em', marginBottom: '10px' }}>⚔️</div>
        <h3 style={{margin: '10px 0', color: '#e65100'}}>Match in Progress</h3>
        <p style={{fontSize: '1.2em', fontWeight: 'bold'}}>
          You vs <span style={{color: '#d84315'}}>{matchStatus.opponent}</span>
        </p>
        <div style={{ fontSize: '0.9em', color: '#666', marginTop: '10px' }}>
          Match ID: {matchStatus.match_id} | Table: {matchStatus.table_id}
        </div>
      </div>
      
      <form onSubmit={handleSubmit}>
        <div style={{marginBottom: '20px'}}>
          <p style={{fontSize: '0.9rem', color: '#666', marginBottom: '15px', textAlign: 'center'}}>
            Enter final scores (0-8 balls):
          </p>
          
          <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px'}}>
            <div style={{textAlign: 'center'}}>
              <label style={{fontSize: '0.9rem', display: 'block', marginBottom: '8px', fontWeight: 'bold', color: '#2e7d32'}}>
                Your Score
              </label>
              <input 
                type="number" 
                min="0" 
                max="8" 
                value={myBalls}
                onChange={(e) => setMyBalls(e.target.value)}
                placeholder="0-8"
                style={{...inputStyle, textAlign: 'center', fontSize: '1.5em', padding: '15px'}}
                required
              />
            </div>
            <div style={{textAlign: 'center'}}>
              <label style={{fontSize: '0.9rem', display: 'block', marginBottom: '8px', fontWeight: 'bold', color: '#d32f2f'}}>
                {matchStatus.opponent}'s Score
              </label>
              <input 
                type="number" 
                min="0" 
                max="8" 
                value={oppBalls}
                onChange={(e) => setOppBalls(e.target.value)}
                placeholder="0-8"
                style={{...inputStyle, textAlign: 'center', fontSize: '1.5em', padding: '15px'}}
                required
              />
            </div>
          </div>
        </div>

        <div style={{display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px', marginBottom: '15px'}}>
          <button 
            type="button" 
            onClick={() => {
              setMyBalls('8');
              setOppBalls('0');
            }}
            style={{...btnPrimaryStyle, background: '#4caf50', padding: '12px'}}
          >
            Win 8-0
          </button>
          <button 
            type="button" 
            onClick={() => {
              setMyBalls('7');
              setOppBalls('1');
            }}
            style={{...btnPrimaryStyle, background: '#4caf50', padding: '12px'}}
          >
            Win 7-1
          </button>
          <button 
            type="button" 
            onClick={() => {
              setMyBalls('0');
              setOppBalls('8');
            }}
            style={{...btnPrimaryStyle, background: '#f44336', padding: '12px'}}
          >
            Lose 0-8
          </button>
          <button 
            type="button" 
            onClick={() => {
              setMyBalls('1');
              setOppBalls('7');
            }}
            style={{...btnPrimaryStyle, background: '#f44336', padding: '12px'}}
          >
            Lose 1-7
          </button>
        </div>

        <button 
          type="submit" 
          style={{...btnPrimaryStyle, marginTop: '15px', background: '#ff9800', padding: '15px', fontSize: '1.1em'}}
          disabled={disabled}
        >
          {disabled ? 'Submitting...' : 'Submit Match Results'}
        </button>
      </form>
    </div>
  );
}

// Styles
const inputStyle = { 
  display: 'block', 
  width: '100%', 
  marginBottom: '10px', 
  padding: '12px', 
  border: '1px solid #ccc', 
  borderRadius: '6px',
  boxSizing: 'border-box'
};

const btnPrimaryStyle = { 
  width: '100%', 
  padding: '12px', 
  backgroundColor: '#0277bd', 
  color: 'white', 
  border: 'none', 
  borderRadius: '6px', 
  fontSize: '1rem', 
  cursor: 'pointer', 
  fontWeight: 'bold',
  transition: 'background-color 0.3s'
};

const cardStyle = { 
  background: 'white', 
  color: '#333', 
  padding: '25px', 
  borderRadius: '12px', 
  boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
  transition: 'transform 0.2s'
};

const authCardStyle = { 
  maxWidth: '400px', 
  margin: '0 auto', 
  background: 'white', 
  color: '#333', 
  padding: '30px', 
  borderRadius: '12px', 
  boxShadow: '0 10px 30px rgba(0,0,0,0.2)' 
};

const authHeaderStyle = { 
  display: 'flex', 
  alignItems: 'center', 
  gap: '10px', 
  marginBottom: '20px' 
};

const linkBtnStyle = { 
  marginTop: '15px', 
  background: 'none', 
  border: 'none', 
  color: '#0277bd', 
  cursor: 'pointer', 
  textDecoration: 'underline', 
  width: '100%', 
  textAlign: 'center',
  padding: '10px'
};

const logoutBtnStyle = {
  background: 'none',
  border: '1px solid #fff',
  color: '#fff',
  padding: '8px 16px',
  borderRadius: '4px',
  cursor: 'pointer',
  fontWeight: 'bold'
};

export default App;