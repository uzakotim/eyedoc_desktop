import { useState, useEffect, useCallback, useRef } from 'react'
import './App.css'

export default function App() {
  const [streamPort, setStreamPort] = useState(() => {
    const params = new URLSearchParams(window.location.search)
    return params.get('stream_port') || '5234'
  })

  const [frameSrc, setFrameSrc] = useState('')
  const [status, setStatus] = useState({
    connected: false,
    streaming: true,
    mirror: true,
    camera_index: 0,
    fps: 0,
    error: null,
  })

  const [isRetrying, setIsRetrying] = useState(false)
  const [showControls, setShowControls] = useState(false)
  const prevBlobUrlRef = useRef(null)

  // Initialize port from pywebview API if available
  useEffect(() => {
    const initConfig = async () => {
      if (window.pywebview?.api?.get_config) {
        try {
          const config = await window.pywebview.api.get_config()
          if (config?.stream_port) {
            setStreamPort(String(config.stream_port))
          }
        } catch (e) {
          console.warn('[EyeDoc] Could not fetch pywebview config:', e)
        }
      }
    }
    initConfig()
  }, [])

  // Poll camera status periodically
  useEffect(() => {
    const checkStatus = async () => {
      if (window.pywebview?.api?.get_camera_status) {
        try {
          const s = await window.pywebview.api.get_camera_status()
          if (s) setStatus(s)
        } catch (e) {
          // Silent fallback
        }
      }
    }

    checkStatus()
    const intervalId = setInterval(checkStatus, 1500)

    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        handleHide()
      }
    }
    window.addEventListener('keydown', handleKeyDown)

    return () => {
      clearInterval(intervalId)
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [])

  // Active Frame Fetcher: Guarantees 100% rendering in WKWebView (Safari/macOS) & WebView2 (Windows)
  useEffect(() => {
    let active = true
    let inFlight = false

    const fetchNextFrame = async () => {
      if (!active || inFlight) return
      inFlight = true

      try {
        const res = await fetch(`http://127.0.0.1:${streamPort}/snapshot.jpg?t=${Date.now()}`)
        if (res.ok) {
          const blob = await res.blob()
          if (!active) return

          const newUrl = URL.createObjectURL(blob)
          setFrameSrc(newUrl)

          if (prevBlobUrlRef.current) {
            URL.revokeObjectURL(prevBlobUrlRef.current)
          }
          prevBlobUrlRef.current = newUrl
        }
      } catch (err) {
        // Transient network delay
      } finally {
        inFlight = false
        if (active) {
          setTimeout(fetchNextFrame, 30) // ~30 FPS
        }
      }
    }

    fetchNextFrame()

    return () => {
      active = false
      if (prevBlobUrlRef.current) {
        URL.revokeObjectURL(prevBlobUrlRef.current)
        prevBlobUrlRef.current = null
      }
    }
  }, [streamPort])

  const handleHide = useCallback(async () => {
    if (window.pywebview?.api?.hide_window) {
      try {
        await window.pywebview.api.hide_window()
      } catch (e) {
        console.error(e)
      }
    }
  }, [])

  const handleToggleMirror = async (e) => {
    e.stopPropagation()
    if (window.pywebview?.api?.toggle_mirror) {
      try {
        const newMirror = await window.pywebview.api.toggle_mirror()
        setStatus((prev) => ({ ...prev, mirror: newMirror }))
      } catch (e) {
        console.error(e)
      }
    }
  }

  const handleToggleCamera = async (e) => {
    e.stopPropagation()
    if (window.pywebview?.api?.toggle_camera) {
      try {
        const newStreaming = await window.pywebview.api.toggle_camera()
        setStatus((prev) => ({ ...prev, streaming: newStreaming }))
      } catch (e) {
        console.error(e)
      }
    }
  }

  const handleSwitchCamera = async (e) => {
    e.stopPropagation()
    if (window.pywebview?.api?.switch_camera) {
      try {
        const res = await window.pywebview.api.switch_camera()
        if (res?.camera_index !== undefined) {
          setStatus((prev) => ({ ...prev, camera_index: res.camera_index, connected: false }))
        }
      } catch (e) {
        console.error(e)
      }
    }
  }

  const handleRetry = async (e) => {
    e.stopPropagation()
    setIsRetrying(true)
    if (window.pywebview?.api?.retry_camera) {
      try {
        await window.pywebview.api.retry_camera()
      } catch (e) {
        console.error(e)
      }
    }
    setTimeout(() => setIsRetrying(false), 1200)
  }

  return (
    <div
      className="w-full h-full flex flex-col p-1.5 select-none font-sans"
      onMouseEnter={() => setShowControls(true)}
      onMouseLeave={() => setShowControls(false)}
    >
      {/* Outer rounded container with glowing glassmorphic background */}
      <div className="w-full h-full flex flex-col rounded-2xl bg-slate-950/92 backdrop-blur-2xl border border-white/15 shadow-[0_12px_36px_rgba(0,0,0,0.65),0_0_0_1px_rgba(255,255,255,0.06)] overflow-hidden">
        {/* Header bar (Drag Region) */}
        <header className="drag-region pywebview-drag-region h-9 min-h-[36px] px-3 flex items-center justify-between border-b border-white/10 bg-slate-900/60 cursor-grab active:cursor-grabbing">
          {/* Left: Branding & Status Dot */}
          <div className="flex items-center gap-2 pointer-events-none">
            <div className="relative flex items-center justify-center">
              <span
                className={`w-2.5 h-2.5 rounded-full ${
                  status.connected && status.streaming
                    ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)] animate-pulse'
                    : 'bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.6)]'
                }`}
              />
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-xs font-semibold tracking-tight text-white/90">
                EyeDoc
              </span>
              <span className="text-[10px] px-1.5 py-0.2 rounded-full bg-indigo-500/20 text-indigo-300 font-medium border border-indigo-500/30">
                Cam #{status.camera_index ?? 0}
              </span>
            </div>
          </div>

          {/* Right: Quick Action Buttons (No-drag) */}
          <div className="no-drag flex items-center gap-1">
            {/* Switch Camera Index Button */}
            <button
              onClick={handleSwitchCamera}
              title={`Switch camera index (current: #${status.camera_index ?? 0})`}
              className="px-1.5 py-0.5 rounded-md text-[11px] font-semibold text-white/60 hover:text-white hover:bg-white/10 border border-white/10 transition-colors"
            >
              #{status.camera_index ?? 0} ⇄
            </button>

            {/* Mirror Toggle Button */}
            <button
              onClick={handleToggleMirror}
              title={status.mirror ? 'Mirror: On' : 'Mirror: Off'}
              className={`p-1 rounded-md text-xs transition-colors ${
                status.mirror
                  ? 'text-indigo-400 bg-indigo-500/15 hover:bg-indigo-500/25'
                  : 'text-white/50 hover:text-white/90 hover:bg-white/10'
              }`}
            >
              <svg
                className="w-3.5 h-3.5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M12 20v2" />
                <path d="M12 14v2" />
                <path d="M12 8v2" />
                <path d="M12 2v2" />
                <path d="m3 7 5 5-5 5V7z" />
                <path d="m21 7-5 5 5 5V7z" />
              </svg>
            </button>

            {/* Camera Pause/Resume */}
            <button
              onClick={handleToggleCamera}
              title={status.streaming ? 'Pause Camera' : 'Resume Camera'}
              className={`p-1 rounded-md text-xs transition-colors ${
                status.streaming
                  ? 'text-white/60 hover:text-white hover:bg-white/10'
                  : 'text-amber-400 bg-amber-500/20 hover:bg-amber-500/30'
              }`}
            >
              {status.streaming ? (
                <svg
                  className="w-3.5 h-3.5"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z" />
                  <circle cx="12" cy="13" r="3" />
                </svg>
              ) : (
                <svg
                  className="w-3.5 h-3.5"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <line x1="2" y1="2" x2="22" y2="22" />
                  <path d="M10.41 10.41a2 2 0 1 0 2.83 2.83" />
                  <path d="M13.5 4h-4L7.5 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h14.5" />
                  <path d="M21.5 16.5V9a2 2 0 0 0-2-2h-2.5l-.83-1" />
                </svg>
              )}
            </button>

            {/* Close / Hide Button */}
            <button
              onClick={handleHide}
              title="Hide to system tray (Esc)"
              className="p-1 rounded-md text-white/50 hover:text-rose-400 hover:bg-rose-500/20 transition-colors ml-0.5"
            >
              <svg
                className="w-3.5 h-3.5"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M18 6 6 18" />
                <path d="m6 6 12 12" />
              </svg>
            </button>
          </div>
        </header>

        {/* Video Viewport Container */}
        <div className="relative flex-1 m-2 rounded-xl bg-slate-900/90 overflow-hidden border border-white/10 flex items-center justify-center">
          {/* Live Video Feed Image */}
          {frameSrc ? (
            <img
              src={frameSrc}
              alt="Front camera video stream"
              className="w-full h-full object-cover select-none pointer-events-none"
            />
          ) : (
            <div className="flex flex-col items-center justify-center text-white/50 gap-2">
              <span className="w-6 h-6 border-2 border-indigo-400/40 border-t-indigo-400 rounded-full animate-spin" />
              <span className="text-[11px]">Connecting camera...</span>
            </div>
          )}

          {/* Floating HUD Badges */}
          <div
            className={`absolute inset-x-2 top-2 flex justify-between pointer-events-none transition-opacity duration-200 ${
              showControls ? 'opacity-100' : 'opacity-85'
            }`}
          >
            {/* Live Indicator Badge */}
            <span
              className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold tracking-wider backdrop-blur-md ${
                status.connected && status.streaming
                  ? 'bg-emerald-950/80 text-emerald-300 border border-emerald-500/40'
                  : 'bg-amber-950/80 text-amber-300 border border-amber-500/40'
              }`}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  status.connected && status.streaming
                    ? 'bg-emerald-400 animate-ping'
                    : 'bg-amber-400'
                }`}
              />
              {status.connected && status.streaming ? 'LIVE' : 'STANDBY'}
            </span>

            {/* FPS Badge */}
            {status.connected && (
              <span className="px-2 py-0.5 rounded-full text-[10px] font-medium text-white/70 bg-black/60 backdrop-blur-md border border-white/10">
                {status.fps > 0 ? `${status.fps} FPS` : '30 FPS'}
              </span>
            )}
          </div>

          {/* Fallback Action Overlay if camera not connected */}
          {!status.connected && (
            <div className="absolute inset-x-3 bottom-3 flex items-center justify-between p-2 rounded-lg bg-slate-900/85 backdrop-blur-md border border-white/15 text-xs text-white/80 no-drag">
              <span className="text-[11px] text-white/70 truncate mr-2">
                {status.error || 'Waiting for camera access...'}
              </span>
              <button
                onClick={handleRetry}
                disabled={isRetrying}
                className="px-2 py-1 rounded bg-indigo-600 hover:bg-indigo-500 active:scale-95 text-white text-[11px] font-medium transition-all flex items-center gap-1 shrink-0"
              >
                {isRetrying ? (
                  <span className="animate-spin text-xs">↻</span>
                ) : (
                  'Retry'
                )}
              </button>
            </div>
          )}
        </div>

        {/* Footer info bar */}
        <footer className="h-6 min-h-[24px] px-3 flex items-center justify-between text-[10px] text-white/40 border-t border-white/5 bg-slate-950/80">
          <span className="flex items-center gap-1">
            <span className="w-1 h-1 rounded-full bg-indigo-400/60" />
            OpenCV Video Feed
          </span>
          <span className="text-white/30">Click tray icon or Esc to hide</span>
        </footer>
      </div>
    </div>
  )
}
