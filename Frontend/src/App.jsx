import React, { useState, useEffect } from 'react';
import { Trophy, Users, LogIn, PlayCircle, ArrowRight } from 'lucide-react';

const API_BASE = "http://127.0.0.1:5000";

function App() {
  const [view, setView] = useState('login'); 
  const [leaderboard, setLeaderboard] = useState([]);
  const [queue, setQueue] = useState([]);
  const [user, setUser] = useState(null); 
  const [matchStatus, setMatchStatus] = useState({ status: 'idle' });

  // --- 1. DATA FETCHING ---
const fetchData = async () => {
  try {
    // 1. Public Data (Always works)
    const lbRes = await fetch(`${API_BASE}/leaderboard`);
    if (lbRes.ok) setLeaderboard(await lbRes.json());

    const qRes = await fetch(`${API_BASE}/queue/1`);
    if (qRes.ok) setQueue(await qRes.json());

    // 2. Protected Data
    // Retrieve token RIGHT BEFORE the fetch
    const token = localStorage.getItem('token'); 

    if (user && token) {
      const sRes = await fetch(`${API_BASE}/match/status`, { 
        headers: {
          'Authorization': `Bearer ${token}`, // Ensure this is exactly 'Bearer ' + token
          'Content-Type': 'application/json'
        }
      });

      if (sRes.ok) {
        const data = await sRes.json();
        setMatchStatus(data);
      } else {
        // If the server says 401, it means the token expired or is invalid
        console.warn("Match status unauthorized");
        setMatchStatus({ status: 'idle' });
      }
    }
  } catch (err) {
    console.error("Fetch error:", err);
  }
};

// Use this updated Effect to prevent unnecessary spamming
useEffect(() => {
  fetchData();
  const interval = setInterval(() => {
    // Only fetch if the page is visible or user is active
    if (user) fetchData(); 
  }, 5000);
  
  return () => clearInterval(interval);
}, [user]);

  // --- 2. ACTIONS ---
  const handleRegister = async (e) => {
  e.preventDefault();
  const formData = {
    username: e.target.username.value,
    first_name: e.target.firstname.value,
    last_name: e.target.lastname.value,
    password: e.target.password.value
  };

  const res = await fetch(`${API_BASE}/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(formData)
  });

  if (res.ok) {
    alert("Registration successful! Please login.");
    setView('login');
  } else {
    alert("Registration failed.");
  }
};

  const handleLogin = async (e) => {
    e.preventDefault(); 
    const username = e.target.username.value;
    const password = e.target.password.value;

    const res = await fetch(`${API_BASE}/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ username, password })
    });

    if (res.ok) {
  const data = await res.json();
  // 1. Save token
  localStorage.setItem('token', data.access_token);
  // 2. Set user (this triggers the useEffect)
  setUser({ user_id: data.user_id, username: data.username });
  // 3. Move view
  setView('select-league');
} else {
      alert("Login Failed: Check username/password");
    }
  };

  const handleJoinQueue = async () => {
    const token = localStorage.getItem('token');
    const res = await fetch(`${API_BASE}/queue/join`, {
      method: 'POST',
      headers: { 
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}` // Added token here too
      },
      credentials: 'include',
      body: JSON.stringify({ table_id: 1 })
    });

    if (res.ok) {
      fetchData();
    } else {
      const err = await res.json();
      alert("Error: " + err.message);
    }
  };

  const handleLogout = async () => {
    await fetch(`${API_BASE}/logout`, { method: 'POST', credentials: 'include' });
    localStorage.removeItem('token'); // Clear token on logout
    setUser(null);
    setView('login');
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
      
      <h1 style={{textAlign: 'center', marginBottom: '30px'}}>🎱 Billiards League</h1>

      {view === 'login' && (
        <div style={authCardStyle}>
          <h2 style={authHeaderStyle}><LogIn size={24}/> Login</h2>
          <form onSubmit={handleLogin}>
            <input name="username" placeholder="Username" required style={inputStyle} />
            <input name="password" type="password" placeholder="Password" required style={inputStyle} />
            <button type="submit" style={btnPrimaryStyle}>Enter League</button>
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
            <button type="submit" style={{...btnPrimaryStyle, backgroundColor: '#2e7d32'}}>Create Account</button>
          </form>
          <button onClick={() => setView('login')} style={linkBtnStyle}>
            Already have an account? Login
          </button>
        </div>
      )}

      {view === 'select-league' && (
        <div style={{ maxWidth: '600px', margin: '0 auto', textAlign: 'center' }}>
          <h2>Welcome, {user?.username}!</h2>
          <p>Choose your league to enter:</p>
          <div style={{ display: 'grid', gap: '15px', marginTop: '20px' }}>
            <div onClick={() => setView('dashboard')} style={cardSelectStyle}>
              <h3>🏆 Competitive 8-Ball</h3>
              <p>Ranked matches. Official rules.</p>
              <ArrowRight color="#0277bd" />
            </div>
          </div>
          <button onClick={handleLogout} style={{ marginTop: '30px', background: 'none', border: 'none', color: '#fff', textDecoration: 'underline', cursor: 'pointer' }}>Logout</button>
        </div>
      )}

      {view === 'dashboard' && (
        <div style={{ maxWidth: '1000px', margin: '0 auto' }}>
          <button onClick={() => setView('select-league')} style={{marginBottom:'10px', background:'none', border:'none', color:'#fff', cursor:'pointer'}}>← Back to Leagues</button>
          
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '20px' }}>
            
            {/* ACTION CARD */}
            <div style={cardStyle}>
              <h2>Status</h2>
              {matchStatus?.status === 'playing' ? (
                <div style={{ backgroundColor: '#fff3e0', padding: '15px', borderRadius: '8px', border: '1px solid #ff9800', color: '#e65100' }}>
                  <PlayCircle style={{verticalAlign: 'middle'}}/> <strong>MATCH ACTIVE</strong><br/>
                  Opponent: {matchStatus.opponent}<br/>
                  <small>Score updates automatically.</small>
                </div>
              ) : (
                <div>
                   <p>You are currently idle.</p>
                   <button onClick={handleJoinQueue} style={btnDangerStyle}>Join Table 1 Queue</button>
                </div>
              )}
            </div>

            {/* QUEUE CARD */}
            <div style={cardStyle}>
              <h2><Users size={20}/> Waiting List (Table 1)</h2>
              {queue.length === 0 ? <p style={{color:'#888'}}>Queue is empty.</p> : (
                queue.map((q, idx) => ( 
                  <div key={idx} style={{ padding: '10px', borderBottom: '1px solid #eee', display: 'flex', justifyContent: 'space-between' }}>
                    <span>
                      <strong style={{ color: '#000000', marginRight: '10px' }}>#{idx + 1}</strong> 
                      {q.username}
                    </span>
                  </div>
                ))
              )}
            </div>
          </div>

          {/* LEADERBOARD CARD */}
          <div style={{ ...cardStyle, marginTop: '20px' }}>
            <h2><Trophy size={20} color="#ff9800"/> Live Rankings</h2>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr style={{borderBottom:'2px solid #eee'}}>
                  <th style={{padding:'10px', textAlign:'left'}}>Rank</th>
                  <th style={{padding:'10px', textAlign:'left'}}>Player</th>
                  <th style={{padding:'10px', textAlign:'left'}}>ELO</th>
                  <th style={{padding:'10px', textAlign:'left'}}>W-L</th>
                </tr>
              </thead>
              <tbody>
                {leaderboard.map((p, idx) => (
                  <tr key={p.username} style={{borderBottom:'1px solid #f0f0f0'}}>
                    <td style={{padding:'10px'}}>#{idx + 1}</td>
                    <td style={{padding:'10px'}}><strong>{p.username}</strong></td>
                    <td style={{padding:'10px'}}>{p.elo_rating}</td>
                    <td style={{padding:'10px'}}>{p.total_wins} - {p.total_losses}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

// Styles remain the same...
const inputStyle = { display: 'block', width: '100%', marginBottom: '10px', padding: '12px', border: '1px solid #ccc', borderRadius: '6px' };
const btnPrimaryStyle = { width: '100%', padding: '12px', backgroundColor: '#0277bd', color: 'white', border: 'none', borderRadius: '6px', fontSize: '1rem', cursor: 'pointer', fontWeight: 'bold' };
const btnDangerStyle = { width: '100%', padding: '12px', backgroundColor: '#d32f2f', color: 'white', border: 'none', borderRadius: '6px', fontSize: '1rem', cursor: 'pointer', fontWeight: 'bold' };
const cardStyle = { background: 'white', color: '#333', padding: '20px', borderRadius: '12px', boxShadow: '0 4px 6px rgba(0,0,0,0.1)' };
const cardSelectStyle = { background: 'white', color: '#333', padding: '20px', borderRadius: '12px', cursor: 'pointer', display:'flex', alignItems:'center', justifyContent:'space-between', transition: 'transform 0.2s' };
const authCardStyle = { maxWidth: '400px', margin: '0 auto', background: 'white', color: '#333', padding: '30px', borderRadius: '12px', boxShadow: '0 10px 25px rgba(0,0,0,0.2)' };
const authHeaderStyle = { display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '20px' };
const linkBtnStyle = { marginTop: '15px', background: 'none', border: 'none', color: '#0277bd', cursor: 'pointer', textDecoration: 'underline', width: '100%', textAlign: 'center' };

export default App;