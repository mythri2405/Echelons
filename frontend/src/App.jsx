import { Routes, Route } from "react-router-dom";

import Sidebar from "./components/Sidebar";
import Header from "./components/Header";

import Dashboard from "./pages/Dashboard";
import LiveFeed from "./pages/LiveFeed";
import Detections from "./pages/Detections";
import MapPage from "./pages/MapPage";
import Alerts from "./pages/Alerts";
import History from "./pages/History";
import Assistant from "./pages/Assistant";

function App() {
  return (
    <div className="app">

      <Sidebar />

      <main className="main">

        <Header />

        <div className="page-content">

          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/live" element={<LiveFeed />} />
            <Route path="/detections" element={<Detections />} />
            <Route path="/map" element={<MapPage />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/history" element={<History />} />
            <Route path="/assistant" element={<Assistant />} />
          </Routes>

        </div>

      </main>

    </div>
  );
}

export default App;