#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
play = root / "src/app/play/page.tsx"
menu = root / "src/components/UserMenu.tsx"

if not play.exists() or not menu.exists():
    raise SystemExit("ERROR: smart-volume targets are missing")

MARKER = "MoonTV Custom Smart Volume V1.8.1"

def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"ERROR: smart-volume target {label!r} expected exactly once, found {count}. "
            "Upstream changed; stop instead of guessing."
        )
    return text.replace(old, new, 1)

# ---------------------------------------------------------------------------
# Playback engine
# ---------------------------------------------------------------------------
play_text = play.read_text(encoding="utf-8")

if MARKER not in play_text:
    refs_old = """  const artPlayerRef = useRef<any>(null);
  const artRef = useRef<HTMLDivElement | null>(null);"""

    refs_new = """  const artPlayerRef = useRef<any>(null);
  const artRef = useRef<HTMLDivElement | null>(null);

  // MoonTV Custom Smart Volume V1.8.1
  type SmartVolumeMode = 'off' | 'soft' | 'strong';
  type SmartVolumeGraph = {
    video: HTMLVideoElement;
    context: AudioContext;
    source: MediaElementAudioSourceNode;
    analyser: AnalyserNode;
    gain: GainNode;
    compressor: DynamicsCompressorNode;
    samples: Float32Array;
    rafId: number | null;
    mode: SmartVolumeMode;
    smoothedGainDb: number;
    lastSampleAt: number;
  };

  const smartVolumeRef = useRef<SmartVolumeGraph | null>(null);
  const smartVolumeArmCleanupRef = useRef<(() => void) | null>(null);

  const getSmartVolumeMode = (): SmartVolumeMode => {
    if (typeof window === 'undefined') return 'soft';
    const saved = localStorage.getItem('smartVolumeMode');
    return saved === 'off' || saved === 'strong' ? saved : 'soft';
  };

  const getSmartVolumeLabel = (mode: SmartVolumeMode) =>
    mode === 'off' ? '关闭' : mode === 'strong' ? '强力' : '柔和';

  const configureSmartVolumeGraph = (
    graph: SmartVolumeGraph,
    mode: SmartVolumeMode
  ) => {
    graph.mode = mode;
    const now = graph.context.currentTime;

    if (mode === 'off') {
      graph.gain.gain.setTargetAtTime(1, now, 0.08);
      graph.compressor.threshold.setValueAtTime(0, now);
      graph.compressor.knee.setValueAtTime(0, now);
      graph.compressor.ratio.setValueAtTime(1, now);
      graph.compressor.attack.setValueAtTime(0.01, now);
      graph.compressor.release.setValueAtTime(0.15, now);
      graph.smoothedGainDb = 0;
      return;
    }

    if (mode === 'strong') {
      graph.compressor.threshold.setValueAtTime(-24, now);
      graph.compressor.knee.setValueAtTime(24, now);
      graph.compressor.ratio.setValueAtTime(5, now);
      graph.compressor.attack.setValueAtTime(0.01, now);
      graph.compressor.release.setValueAtTime(0.35, now);
    } else {
      graph.compressor.threshold.setValueAtTime(-18, now);
      graph.compressor.knee.setValueAtTime(18, now);
      graph.compressor.ratio.setValueAtTime(3, now);
      graph.compressor.attack.setValueAtTime(0.015, now);
      graph.compressor.release.setValueAtTime(0.28, now);
    }
  };

  const cleanupSmartVolume = () => {
    smartVolumeArmCleanupRef.current?.();
    smartVolumeArmCleanupRef.current = null;

    const graph = smartVolumeRef.current;
    smartVolumeRef.current = null;
    if (!graph) return;

    if (graph.rafId !== null) {
      cancelAnimationFrame(graph.rafId);
    }

    try {
      graph.source.disconnect();
      graph.analyser.disconnect();
      graph.gain.disconnect();
      graph.compressor.disconnect();
    } catch {
      // A node may already be disconnected during player teardown.
    }

    void graph.context.close().catch(() => undefined);
  };

  const canUseSmartVolumeForVideo = (video: HTMLVideoElement) => {
    if (typeof window === 'undefined') return false;
    const src = video.currentSrc || video.src || videoUrl || '';
    if (!src) return false;
    if (src.startsWith('blob:') || src.startsWith('data:')) return true;

    try {
      const parsed = new URL(src, window.location.href);
      if (parsed.origin === window.location.origin) return true;
      // Cross-origin media is only routed through Web Audio when the media
      // element is explicitly CORS-enabled. Otherwise keep native audio.
      return video.crossOrigin === 'anonymous';
    } catch {
      return false;
    }
  };

  const startSmartVolumeLoop = (graph: SmartVolumeGraph) => {
    const tick = (time: number) => {
      if (smartVolumeRef.current !== graph) return;

      if (
        graph.mode !== 'off' &&
        time - graph.lastSampleAt >= 120 &&
        !graph.video.paused &&
        !graph.video.muted
      ) {
        graph.lastSampleAt = time;
        graph.analyser.getFloatTimeDomainData(graph.samples);

        let sumSquares = 0;
        for (let i = 0; i < graph.samples.length; i += 1) {
          const sample = graph.samples[i];
          sumSquares += sample * sample;
        }

        const rms = Math.sqrt(sumSquares / Math.max(1, graph.samples.length));
        if (rms > 0.0018) {
          const currentDb = 20 * Math.log10(rms);
          const targetDb = graph.mode === 'strong' ? -20 : -22;
          const maxBoostDb = graph.mode === 'strong' ? 6 : 4;
          const maxCutDb = graph.mode === 'strong' ? -8 : -6;
          const desiredGainDb = Math.max(
            maxCutDb,
            Math.min(maxBoostDb, targetDb - currentDb)
          );

          // Slow adaptation avoids audible pumping between dialogue/music.
          graph.smoothedGainDb =
            graph.smoothedGainDb * 0.9 + desiredGainDb * 0.1;
          const linearGain = Math.pow(10, graph.smoothedGainDb / 20);
          graph.gain.gain.setTargetAtTime(
            linearGain,
            graph.context.currentTime,
            graph.mode === 'strong' ? 0.1 : 0.16
          );
        }
      }

      graph.rafId = requestAnimationFrame(tick);
    };

    graph.rafId = requestAnimationFrame(tick);
  };

  const applySmartVolumeMode = async (
    mode: SmartVolumeMode
  ): Promise<boolean> => {
    const video = artPlayerRef.current?.video as HTMLVideoElement | undefined;
    if (!video) return false;

    const existing = smartVolumeRef.current;
    if (existing?.video === video) {
      configureSmartVolumeGraph(existing, mode);
      return true;
    }

    if (mode === 'off') return true;

    if (existing) {
      cleanupSmartVolume();
    }

    if (!canUseSmartVolumeForVideo(video)) {
      console.info(
        '[SmartVolume] 当前为不可安全接管的跨域直连媒体，保持原声播放。'
      );
      return false;
    }

    const AudioContextCtor =
      window.AudioContext || (window as any).webkitAudioContext;
    if (!AudioContextCtor) {
      console.info('[SmartVolume] 当前浏览器不支持 Web Audio，保持原声播放。');
      return false;
    }

    let context: AudioContext | null = null;
    try {
      context = new AudioContextCtor() as AudioContext;
      if (context.state === 'suspended') {
        await context.resume();
      }

      // Do not reroute audio into a suspended context. This is the critical
      // fallback that prevents autoplay policies from causing silent video.
      if (context.state !== 'running') {
        await context.close().catch(() => undefined);
        return false;
      }

      const source = context.createMediaElementSource(video);
      const analyser = context.createAnalyser();
      const gain = context.createGain();
      const compressor = context.createDynamicsCompressor();

      analyser.fftSize = 1024;
      analyser.smoothingTimeConstant = 0.75;

      source.connect(analyser);
      analyser.connect(gain);
      gain.connect(compressor);
      compressor.connect(context.destination);

      const graph: SmartVolumeGraph = {
        video,
        context,
        source,
        analyser,
        gain,
        compressor,
        samples: new Float32Array(analyser.fftSize),
        rafId: null,
        mode,
        smoothedGainDb: 0,
        lastSampleAt: 0,
      };

      smartVolumeRef.current = graph;
      configureSmartVolumeGraph(graph, mode);
      startSmartVolumeLoop(graph);
      console.log(
        '[SmartVolume] 已启用：' + getSmartVolumeLabel(mode)
      );
      return true;
    } catch (error) {
      console.warn('[SmartVolume] 初始化失败，已保持原声播放:', error);
      if (context) {
        await context.close().catch(() => undefined);
      }
      smartVolumeRef.current = null;
      return false;
    }
  };

  const armSmartVolumeForCurrentPlayer = () => {
    smartVolumeArmCleanupRef.current?.();
    smartVolumeArmCleanupRef.current = null;

    const mode = getSmartVolumeMode();
    if (mode === 'off' || typeof window === 'undefined') return;

    const activate = () => {
      smartVolumeArmCleanupRef.current?.();
      smartVolumeArmCleanupRef.current = null;
      void applySmartVolumeMode(mode);
    };

    if ((navigator as any).userActivation?.hasBeenActive) {
      activate();
      return;
    }

    const cleanup = () => {
      window.removeEventListener('pointerdown', activate, true);
      window.removeEventListener('keydown', activate, true);
      window.removeEventListener('touchstart', activate, true);
    };

    smartVolumeArmCleanupRef.current = cleanup;
    window.addEventListener('pointerdown', activate, {
      once: true,
      capture: true,
    });
    window.addEventListener('keydown', activate, {
      once: true,
      capture: true,
    });
    window.addEventListener('touchstart', activate, {
      once: true,
      capture: true,
    });
  };"""

    play_text = replace_once(
        play_text, refs_old, refs_new, "player refs"
    )

    cleanup_old = """  const cleanupPlayer = async () => {
    revokeCustomSubtitle();"""
    cleanup_new = """  const cleanupPlayer = async () => {
    cleanupSmartVolume();
    revokeCustomSubtitle();"""
    play_text = replace_once(
        play_text, cleanup_old, cleanup_new, "player cleanup"
    )

    destroy_old = """        artPlayerRef.current.on('destroy', () => {
          clearPlayerTimeouts();
        });"""
    destroy_new = """        artPlayerRef.current.on('destroy', () => {
          clearPlayerTimeouts();
          cleanupSmartVolume();
        });"""
    play_text = replace_once(
        play_text, destroy_old, destroy_new, "destroy hook"
    )

    ready_old = """          applyProgressThumbConfig();

          // 添加字幕切换和本地字幕上传功能；ASS/SSA/PGS 需要播放器 ready 后挂载专用渲染器"""
    ready_new = """          applyProgressThumbConfig();

          // 智能音量均衡：默认柔和。若浏览器尚无用户手势，先保持原声，
          // 第一次交互后再安全接管，避免 AudioContext 自动播放策略导致静音。
          if (artPlayerRef.current) {
            const currentSmartVolumeMode = getSmartVolumeMode();
            artPlayerRef.current.setting.add({
              name: 'smart-volume',
              html: '智能音量均衡',
              selector: [
                { html: '关闭', value: 'off' },
                { html: '柔和', value: 'soft' },
                { html: '强力', value: 'strong' },
              ],
              onSelect: function (item: any) {
                const nextMode = item.value as SmartVolumeMode;
                localStorage.setItem('smartVolumeMode', nextMode);
                if (nextMode === 'off') {
                  void applySmartVolumeMode('off');
                } else {
                  armSmartVolumeForCurrentPlayer();
                  void applySmartVolumeMode(nextMode);
                }
                return item.html;
              },
              default: getSmartVolumeLabel(currentSmartVolumeMode),
            });
            armSmartVolumeForCurrentPlayer();
          }

          // 添加字幕切换和本地字幕上传功能；ASS/SSA/PGS 需要播放器 ready 后挂载专用渲染器"""
    play_text = replace_once(
        play_text, ready_old, ready_new, "ready smart-volume setting"
    )

required_play = [
    MARKER,
    "name: 'smart-volume'",
    "createDynamicsCompressor()",
    "maxBoostDb = graph.mode === 'strong' ? 6 : 4",
    "cleanupSmartVolume();",
]
missing = [item for item in required_play if item not in play_text]
if missing:
    raise SystemExit(
        "ERROR: smart-volume playback markers missing: " + ", ".join(missing)
    )

play.write_text(play_text, encoding="utf-8")

# ---------------------------------------------------------------------------
# Settings UI
# ---------------------------------------------------------------------------
menu_text = menu.read_text(encoding="utf-8")
MENU_MARKER = "智能音量均衡"

state_old = "  const [bufferStrategy, setBufferStrategy] = useState('medium');"
state_new = """  const [bufferStrategy, setBufferStrategy] = useState('medium');
  const [smartVolumeMode, setSmartVolumeMode] = useState<
    'off' | 'soft' | 'strong'
  >('soft');"""
if "const [smartVolumeMode, setSmartVolumeMode]" not in menu_text:
    menu_text = replace_once(
        menu_text, state_old, state_new, "settings state"
    )

load_old = """      const savedBufferStrategy = localStorage.getItem('bufferStrategy');
      if (savedBufferStrategy !== null) {
        setBufferStrategy(savedBufferStrategy);
      }"""
load_new = """      const savedBufferStrategy = localStorage.getItem('bufferStrategy');
      if (savedBufferStrategy !== null) {
        setBufferStrategy(savedBufferStrategy);
      }

      const savedSmartVolumeMode = localStorage.getItem('smartVolumeMode');
      if (
        savedSmartVolumeMode === 'off' ||
        savedSmartVolumeMode === 'soft' ||
        savedSmartVolumeMode === 'strong'
      ) {
        setSmartVolumeMode(savedSmartVolumeMode);
      } else {
        setSmartVolumeMode('soft');
      }"""
if "const savedSmartVolumeMode" not in menu_text:
    menu_text = replace_once(
        menu_text, load_old, load_new, "settings load"
    )

handler_old = """  const handleBufferStrategyChange = (value: string) => {
    setBufferStrategy(value);
    if (typeof window !== 'undefined') {
      localStorage.setItem('bufferStrategy', value);
    }
  };"""
handler_new = """  const handleBufferStrategyChange = (value: string) => {
    setBufferStrategy(value);
    if (typeof window !== 'undefined') {
      localStorage.setItem('bufferStrategy', value);
    }
  };

  const handleSmartVolumeModeChange = (
    value: 'off' | 'soft' | 'strong'
  ) => {
    setSmartVolumeMode(value);
    if (typeof window !== 'undefined') {
      localStorage.setItem('smartVolumeMode', value);
    }
  };"""
if "handleSmartVolumeModeChange" not in menu_text:
    menu_text = replace_once(
        menu_text, handler_old, handler_new, "settings handler"
    )

reset_anchor = """    setTmdbImageBaseUrl('https://image.tmdb.org');
    setBufferStrategy('medium');
    setNextEpisodePreCache(true);"""
reset_replacement = """    setTmdbImageBaseUrl('https://image.tmdb.org');
    setBufferStrategy('medium');
    setSmartVolumeMode('soft');
    setNextEpisodePreCache(true);"""
if "    setSmartVolumeMode('soft');" not in menu_text:
    menu_text = replace_once(
        menu_text, reset_anchor, reset_replacement, "settings reset state"
    )

storage_old = """      localStorage.setItem('tmdbImageBaseUrl', 'https://image.tmdb.org');
      localStorage.setItem('bufferStrategy', 'medium');
      localStorage.setItem('nextEpisodePreCache', 'true');"""
storage_new = """      localStorage.setItem('tmdbImageBaseUrl', 'https://image.tmdb.org');
      localStorage.setItem('bufferStrategy', 'medium');
      localStorage.setItem('smartVolumeMode', 'soft');
      localStorage.setItem('nextEpisodePreCache', 'true');"""
if "localStorage.setItem('smartVolumeMode', 'soft')" not in menu_text:
    menu_text = replace_once(
        menu_text, storage_old, storage_new, "settings reset storage"
    )

ui_anchor = "                  {/* 下集预缓冲 */}"
ui_block = """                  {/* 智能音量均衡 */}
                  <div className='space-y-3'>
                    <div>
                      <h4 className='text-sm font-medium text-gray-700 dark:text-gray-300'>
                        智能音量均衡
                      </h4>
                      <p className='text-xs text-gray-500 dark:text-gray-400 mt-1'>
                        自动缩小不同片源之间的音量差异。柔和适合日常观看，强力会进一步压低爆音并提升偏小声音；不兼容的跨域直连源会自动保持原声。
                      </p>
                    </div>
                    <div className='grid grid-cols-3 gap-2'>
                      {(
                        [
                          ['off', '关闭'],
                          ['soft', '柔和'],
                          ['strong', '强力'],
                        ] as const
                      ).map(([value, label]) => (
                        <button
                          key={value}
                          type='button'
                          onClick={() => handleSmartVolumeModeChange(value)}
                          className={
                            'px-3 py-2 rounded-lg text-sm border transition-colors ' +
                            (smartVolumeMode === value
                              ? 'bg-green-500 border-green-500 text-white'
                              : 'bg-white dark:bg-gray-800 border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:border-green-400')
                          }
                        >
                          {label}
                          {value === 'soft' && (
                            <span className='block text-[10px] opacity-80 mt-0.5'>
                              推荐
                            </span>
                          )}
                        </button>
                      ))}
                    </div>
                    <p className='text-[11px] text-gray-400 dark:text-gray-500'>
                      修改后重新进入播放页生效；播放页齿轮菜单也可即时切换。
                    </p>
                  </div>

                  {/* 下集预缓冲 */}"""
if "修改后重新进入播放页生效；播放页齿轮菜单也可即时切换。" not in menu_text:
    menu_text = replace_once(
        menu_text, ui_anchor, ui_block, "settings UI"
    )

required_menu = [
    "const [smartVolumeMode, setSmartVolumeMode]",
    "const savedSmartVolumeMode",
    "handleSmartVolumeModeChange",
    "智能音量均衡",
    "localStorage.setItem('smartVolumeMode', 'soft')",
]
missing = [item for item in required_menu if item not in menu_text]
if missing:
    raise SystemExit(
        "ERROR: smart-volume settings markers missing: " + ", ".join(missing)
    )

menu.write_text(menu_text, encoding="utf-8")
print("Smart volume normalization applied safely to player and settings.")
