# EyeDoc Desktop

EyeDoc is a lightweight macOS desktop application designed to protect your vision while working or gaming. It monitors your blink rate in real time, tracks your distance from the screen, and delivers non-intrusive HUD notifications and gentle audio chimes to prevent digital eye strain and dry eyes.

The application combines a high-performance Python backend (MediaPipe, OpenCV, PyObjC, PyWebView) with a sleek React + Tailwind CSS floating overlay window that docks to the macOS menu bar.

---

## ✨ Features

- **Real-Time Blink Detection**: Tracks facial landmarks using Google MediaPipe (`face_landmarker.task`) to calculate Eye Aspect Ratio (EAR) and detect blinks.
- **Low Blink Rate Warnings**: Alerts you when your blink rate drops below a healthy threshold to prevent dry eyes.
- **Screen Distance Alerts**: Estimates distance from the camera to prevent slouching or sitting too close to the display.
- **Non-Intrusive macOS HUD Overlay**: Custom native HUD overlay panels float above full-screen games, workspaces, and media players without stealing focus or interrupting inputs.
- **Subtle Audio Chimes**: Gentle audio feedback synthesized via `sounddevice` to notify you without being disruptive.
- **Floating & Menu Bar Docked UI**: Transparent, frameless PyWebView window with camera preview, mirroring, live stats, and quick toggles.
- **System Tray Integration**: Native menu bar status icon to quickly show, hide, calibrate, or quit the app.

---

## 📋 Prerequisites

Before installing, ensure your environment meets the following requirements:

- **Operating System**: macOS 12 Monterey or higher (tested on Apple Silicon & Intel)
- **Python**: Python 3.10, 3.11, 3.12, 3.13, or 3.14
- **Node.js**: Node.js 18+ (Node 20+ recommended)
- **Package Manager**: [Yarn](https://yarnpkg.com/) or [npm](https://www.npmjs.com/)
- **Hardware**: Working webcam / FaceTime HD camera

---

## 🚀 Installation & Setup

### 1. Clone the Repository

```bash
git clone https://github.com/uzakotim/eyedoc_desktop.git
cd eyedoc_desktop
```

### 2. Set Up Python Virtual Environment

Create and activate a virtual environment, then install Python dependencies:

```bash
# Create virtual environment
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate

# Upgrade pip and install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

> **Note**: Python dependencies include `mediapipe`, `opencv-python`, `pywebview`, `pyobjc` (Cocoa, Quartz, WebKit), `sounddevice`, `bottle`, and `pystray`.

### 3. Install Frontend & Project Dependencies

Install the root runner dependencies and the frontend React application dependencies:

```bash
# Install root package dependencies (concurrently)
yarn install
# (or: npm install)

# Install frontend dependencies
cd frontend
yarn install
# (or: npm install)
cd ..
```

### 4. Verify MediaPipe Model

The facial landmark model `face_landmarker.task` is included in the repository at:

```
backend/models/face_landmarker.task
```

Ensure this file is present and not empty (approx. ~3.7 MB).

---

## 💻 Running the Application (Development Mode)

### Quick Start (Single Command)

From the project root:

```bash
yarn dev
# or: npm run dev
```

This command builds the frontend assets and starts both the Vite dev server (`http://localhost:5173`) and the Python backend (`backend/app.py`) simultaneously.

### Running Backend and Frontend Separately

If you prefer running the components in separate terminal windows for easier debugging:

**Terminal 1 — Frontend (Vite dev server):**
```bash
cd frontend
yarn dev
```

**Terminal 2 — Backend (PyWebView + Camera / AI Engine):**
```bash
source .venv/bin/activate
python backend/app.py
```

When started, the PyWebView window will detect the running Vite development server and load the UI with Hot Module Replacement (HMR).

---

## 📦 Building the Standalone macOS App (`EyeDoc.app`)

You can compile EyeDoc into a native standalone macOS application bundle (`EyeDoc.app`) using PyInstaller.

### Automated Build Script

Run the automated build script from the root directory:

```bash
./build.sh
```

### Manual Build Steps

If you want to run the build steps manually:

```bash
# 1. Activate virtual environment
source .venv/bin/activate

# 2. Build the production frontend assets
cd frontend
yarn build
cd ..

# 3. Bundle with PyInstaller using app.spec
pyinstaller --noconfirm app.spec
```

The resulting application bundle will be located at:
```
dist/EyeDoc.app
```

You can launch it immediately:
```bash
open dist/EyeDoc.app
```

---

## 🔒 Permissions & Security on macOS

EyeDoc requires camera access for blink and distance detection:

1. **Camera Permission**:
   - On the first run, macOS will prompt you: *"EyeDoc requires camera access for the live preview and blink counter."*
   - Click **Allow**.
   - If prompted or accidentally denied, go to **System Settings > Privacy & Security > Camera** and toggle on **EyeDoc** (or your terminal app, e.g. Terminal / iTerm2 / VS Code, when in development mode).

2. **Notifications & Focus Modes**:
   - EyeDoc uses native borderless HUD overlay panels that display on top of full-screen games and apps. No notification permission configuration is required for the floating HUD overlay.

---

## 📂 Project Architecture

```
eyedoc_desktop/
├── backend/
│   ├── app.py                     # Main application entry, PyWebView window, JS API
│   ├── blink_counter_server.py    # MediaPipe landmark analysis, EAR calculation, blink logic
│   ├── camera.py                  # OpenCV camera capture service & MJPEG streaming
│   ├── notifications.py           # Native macOS HUD overlay (PyObjC) & audio alerts
│   ├── stream_server.py           # Bottle HTTP server for MJPEG stream & static dist
│   ├── tray.py                    # macOS system tray / menu bar icon manager
│   └── models/
│       └── face_landmarker.task   # MediaPipe Face Landmarker model
├── frontend/
│   ├── src/                       # React components & UI logic (App.jsx, App.css)
│   ├── public/                    # Static assets
│   ├── package.json               # Frontend dependencies & Vite scripts
│   └── vite.config.js             # Vite configuration with Tailwind CSS
├── app.spec                       # PyInstaller bundle specification for macOS
├── build.sh                       # Production build automation script
├── requirements.txt               # Python backend dependencies
├── package.json                   # Root workspace scripts & dev tooling
└── README.md                      # Documentation & installation instructions
```

---

## 🛠️ Troubleshooting

- **`ModuleNotFoundError: No module named 'mediapipe'` or similar**:
  Ensure you activated the virtual environment (`source .venv/bin/activate`) before running or building.
- **Camera feed is black or shows connection error**:
  Check that no other application (e.g. Zoom, FaceTime) is locking the webcam, and confirm Camera permissions under **System Settings > Privacy & Security > Camera**.
- **Port Conflicts**:
  The backend stream and blink counter server automatically search for open ports starting at `5234`. The Vite dev server defaults to `5173`. Ensure these ports are not blocked by a local firewall.
- **Sound Alert Issues**:
  EyeDoc uses `sounddevice` for synthesized audio alerts. Ensure your default audio output device is connected and functioning.

---

## 📄 License

ISC License

