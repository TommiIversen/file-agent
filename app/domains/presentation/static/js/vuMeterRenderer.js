// @ts-check

/**
 * @typedef {Object} VuTrack
 * @property {string} label
 * @property {number[]} peaks
 */

/* eslint-disable -- global augmentation for TS */
/**
 * @typedef {Object} VuMeterGlobals
 * @property {(el: HTMLCanvasElement) => any} [initVuMeter]
 * @property {(tracks: VuTrack[]) => void} [updateVuMeter]
 * @property {() => void} [clearVuMeter]
 */

/** @type {Window & VuMeterGlobals} */
const _win = /** @type {any} */ (window);
/* eslint-enable */

/**
 * @file VU Meter Canvas Renderer
 *
 * High-performance canvas-based VU meter display that bypasses
 * Alpine.js reactivity for peak level updates.
 *
 * Problem solved:
 *   14 tracks × 18 segments × 2 channels = 504 Alpine :class bindings
 *   evaluated 10×/sec = ~5,040 reactive evaluations/sec.
 *   Replaced by a single canvas paint per requestAnimationFrame.
 *
 * Data flow:
 *   WebSocket → messageHandler → audioStore.updateLevels()
 *     → window.updateVuMeter(tracks)  ← bypasses Alpine reactivity
 *     → canvas requestAnimationFrame loop
 */
(() => {
    'use strict';

    // ── Segment thresholds & colors (22-segment layout) ──────────────

    const SEGS = [
        { t: 0.001, c: '#22c55e' },  // green-500
        { t: 0.002, c: '#22c55e' },
        { t: 0.003, c: '#22c55e' },
        { t: 0.005, c: '#22c55e' },
        { t: 0.008, c: '#22c55e' },
        { t: 0.015, c: '#22c55e' },
        { t: 0.03,  c: '#22c55e' },
        { t: 0.06,  c: '#22c55e' },
        { t: 0.10,  c: '#22c55e' },
        { t: 0.15,  c: '#22c55e' },
        { t: 0.20,  c: '#22c55e' },
        { t: 0.25,  c: '#22c55e' },
        { t: 0.30,  c: '#22c55e' },
        { t: 0.40,  c: '#eab308' },  // yellow-500
        { t: 0.50,  c: '#eab308' },
        { t: 0.60,  c: '#eab308' },
        { t: 0.70,  c: '#f97316' },  // orange-500
        { t: 0.78,  c: '#f97316' },
        { t: 0.85,  c: '#f97316' },
        { t: 0.90,  c: '#ef4444' },  // red-500
        { t: 0.93,  c: '#ef4444' },
        { t: 0.97,  c: '#f55a5a' },  // red-600 + brightness-125
    ];

    const SEG_COUNT = SEGS.length;
    const OFF       = '#4b5563';   // gray-600 (LED off)
    const LABEL_CLR = '#9ca3af';   // gray-400

    // ── Layout constants (CSS pixels) ──────────────────────────────────

    const SW      = 8;    // segment width (mono)
    const SW_S    = 6;    // segment width (stereo, per channel)
    const SH      = 3;    // segment height
    const SG      = 1;    // vertical gap between segments
    const LR_GAP  = 1;    // gap between L/R bars
    const LABEL_W = 10;   // horizontal space for vertical label left of bars
    const PAD_T   = 2;
    const PAD_B   = 2;
    const FONT    = '9px ui-monospace, SFMono-Regular, monospace';

    const BAR_H   = SEG_COUNT * (SH + SG) - SG;   // total bar pixel height
    const TOTAL_H = PAD_T + BAR_H + PAD_B;

    // Peak decay: multiply per frame (~60 fps) → smooth ~12 dB/s falloff
    const DECAY = 0.93;

    // ── Renderer class ─────────────────────────────────────────────────

    class VuMeterRenderer {
        /** @param {HTMLCanvasElement} canvas */
        constructor(canvas) {
            /** @type {HTMLCanvasElement} */
            this._cvs = canvas;
            /** @type {CanvasRenderingContext2D} */
            this._ctx = /** @type {CanvasRenderingContext2D} */ (
                canvas.getContext('2d')
            );
            this._dpr = window.devicePixelRatio || 1;

            /** @type {Array<{label: string, peaks: number[]}>} */
            this._tracks = [];
            /** @type {Float32Array[]} smoothed display values per track */
            this._display = [];

            /** @type {number|null} */
            this._raf = null;
            this._w = 0;
            this._h = 0;

            this._tick = this._tick.bind(this);

            // Repaint on container resize (idle meters would otherwise not update)
            this._ro = new ResizeObserver(() => {
                this._w = 0;  // force _size() recalc
                if (this._raf === null && this._tracks.length > 0) {
                    this._raf = requestAnimationFrame(this._tick);
                }
            });
            if (canvas.parentElement) this._ro.observe(canvas.parentElement);
        }

        /**
         * Feed new peak data (~10 Hz from WebSocket).
         * @param {Array<{label: string, peaks: number[]}>} tracks
         */
        update(tracks) {
            this._tracks = tracks;

            // Grow display array to match track count
            while (this._display.length < tracks.length) {
                this._display.push(new Float32Array(2));
            }

            // Instant attack — decay handles the fall
            for (let i = 0; i < tracks.length; i++) {
                const src = tracks[i].peaks;
                const dst = this._display[i];
                for (let ch = 0; ch < src.length; ch++) {
                    if (src[ch] >= dst[ch]) dst[ch] = src[ch];
                }
            }

            // Kick render loop if not running
            if (this._raf === null) {
                this._raf = requestAnimationFrame(this._tick);
            }
        }

        /** Fade meters to zero (recording stopped). */
        clear() {
            for (const t of this._tracks) {
                for (let i = 0; i < t.peaks.length; i++) t.peaks[i] = 0;
            }
            if (this._raf === null) {
                this._raf = requestAnimationFrame(this._tick);
            }
        }

        destroy() {
            if (this._raf !== null) {
                cancelAnimationFrame(this._raf);
                this._raf = null;
            }
            this._ro.disconnect();
        }

        // ── internals ──────────────────────────────────────────────────

        _tick() {
            this._raf = null;
            this._decay();
            this._size();

            // If parent is still hidden (w=0), retry until visible
            if (this._w < 1 && this._tracks.length > 0) {
                this._raf = requestAnimationFrame(this._tick);
                return;
            }

            this._paint();

            // Continue loop while any peak is still decaying
            if (this._alive()) {
                this._raf = requestAnimationFrame(this._tick);
            }
        }

        _alive() {
            for (let i = 0; i < this._display.length && i < this._tracks.length; i++) {
                const d = this._display[i];
                if (d[0] > 0.001 || d[1] > 0.001) return true;
            }
            return false;
        }

        _decay() {
            for (let i = 0; i < this._tracks.length; i++) {
                const tgt = this._tracks[i].peaks;
                const d = this._display[i];
                for (let ch = 0; ch < tgt.length; ch++) {
                    if (d[ch] > tgt[ch]) {
                        d[ch] *= DECAY;
                        if (d[ch] < 0.001) d[ch] = 0;
                    }
                }
            }
        }

        _size() {
            const p = this._cvs.parentElement;
            if (!p) return;
            const w = p.clientWidth;
            if (w < 1) return;  // container not yet visible

            if (w === this._w && TOTAL_H === this._h) return;
            this._w = w;
            this._h = TOTAL_H;

            this._cvs.style.width  = w + 'px';
            this._cvs.style.height = TOTAL_H + 'px';
            this._cvs.width  = Math.round(w * this._dpr);
            this._cvs.height = Math.round(TOTAL_H * this._dpr);
            this._ctx.setTransform(this._dpr, 0, 0, this._dpr, 0, 0);
        }

        _paint() {
            const ctx = this._ctx;
            const w = this._w;
            const n = this._tracks.length;
            if (!w || !n) return;

            // Clear (transparent — container div provides background)
            ctx.clearRect(0, 0, w, TOTAL_H);

            const slot = w / n;

            for (let t = 0; t < n; t++) {
                const tr = this._tracks[t];
                const dp = this._display[t];
                const cx = slot * t + slot / 2;
                const stereo = tr.peaks.length > 1;

                // Vertical label (top-to-bottom, bottom-aligned, left of bars)
                ctx.save();
                ctx.fillStyle = LABEL_CLR;
                ctx.font = FONT;
                ctx.textAlign = 'right';       // after 90° rotation: bottom-aligned
                ctx.textBaseline = 'bottom';
                const barLeft = stereo
                    ? Math.round(cx - (SW_S * 2 + LR_GAP) / 2)
                    : Math.round(cx - SW / 2);
                const lx = barLeft - 12;
                ctx.translate(lx, PAD_T + BAR_H);
                ctx.rotate(Math.PI / 2);  // 90° clockwise → top-to-bottom
                ctx.fillText(tr.label, 0, 0, BAR_H);
                ctx.restore();

                if (stereo) {
                    const bw = SW_S * 2 + LR_GAP;
                    const x0 = Math.round(cx - bw / 2);
                    this._bar(ctx, x0, SW_S, dp[0]);
                    this._bar(ctx, x0 + SW_S + LR_GAP, SW_S, dp[1]);
                } else {
                    this._bar(ctx, Math.round(cx - SW / 2), SW, dp[0]);
                }
            }
        }

        /**
         * Draw a single vertical bar (bottom-to-top).
         * @param {CanvasRenderingContext2D} ctx
         * @param {number} x
         * @param {number} w
         * @param {number} peak - 0.0 – 1.0
         */
        _bar(ctx, x, w, peak) {
            for (let s = 0; s < SEG_COUNT; s++) {
                // segment 0 = bottom, segment N-1 = top
                const y = PAD_T + (SEG_COUNT - 1 - s) * (SH + SG);
                ctx.fillStyle = peak > SEGS[s].t ? SEGS[s].c : OFF;
                ctx.fillRect(x, y, w, SH);
            }
        }
    }

    // ── Global API (called by audioStore / messageHandler) ─────────────

    /** @type {VuMeterRenderer|null} */
    let _inst = null;

    /**
     * Initialize VU meter renderer on a canvas element.
     * Called from x-init on the canvas in audio_recording_status.html.
     * @param {HTMLCanvasElement} el
     * @returns {VuMeterRenderer}
     */
    _win.initVuMeter = function(el) {
        if (_inst) _inst.destroy();
        _inst = new VuMeterRenderer(el);
        return _inst;
    };

    /**
     * Feed new peak data (called from audioStore.updateLevels).
     * @param {Array<{label: string, peaks: number[]}>} tracks
     */
    _win.updateVuMeter = function(tracks) {
        if (_inst) _inst.update(tracks);
    };

    /**
     * Fade meters to zero (called from audioStore.clearLevels).
     */
    _win.clearVuMeter = function() {
        if (_inst) _inst.clear();
    };
})();
