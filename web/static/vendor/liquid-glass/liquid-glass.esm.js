/**
 * Generic typed EventEmitter.
 *
 * User-facing methods (on / off / once) are fully typed via the event map T.
 * The internal _emit method uses an optional payload so void-like events
 * can be fired without an argument: `_emit('destroy')`.
 *
 * @example
 *   interface MyEvents { click: MouseEvent; destroy: undefined; }
 *   class Foo extends EventEmitter<MyEvents> { ... }
 *
 *   foo.on('click',   (e: MouseEvent) => { ... })
 *   foo.on('destroy', () => { ... })          // no-arg callbacks are fine
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
class EventEmitter {
    constructor() {
        this._ev = new Map();
    }
    on(event, fn) {
        if (!this._ev.has(event))
            this._ev.set(event, new Set());
        this._ev.get(event).add(fn);
        return this;
    }
    off(event, fn) {
        if (!this._ev.has(event))
            return this;
        if (fn)
            this._ev.get(event).delete(fn);
        else
            this._ev.get(event).clear();
        return this;
    }
    once(event, fn) {
        const wrapper = (payload) => {
            this.off(event, wrapper);
            fn(payload);
        };
        return this.on(event, wrapper);
    }
    /**
     * @internal — fire an event.
     * Payload is optional so no-arg events can be fired as `_emit('destroy')`.
     */
    _emit(event, payload) {
        var _a;
        (_a = this._ev.get(event)) === null || _a === void 0 ? void 0 : _a.forEach((fn) => fn(payload));
        return this;
    }
}

/**
 * Core physics for the liquid-glass displacement maps.
 *
 * compute1D  — Snell's law refraction along one radius (128 samples)
 * compute2D  — wraps the 1D map around a rounded-rectangle shape
 * computeSpecular — physically-based rim-light highlight
 */
// ─── Surface profiles ────────────────────────────────────────────────────────
const PROFILES = {
    convexSquircle: (x) => Math.pow(1 - Math.pow(1 - x, 4), 1 / 4),
    convexCircle: (x) => Math.sqrt(Math.max(0, 1 - Math.pow(1 - x, 2))),
    concave: (x) => 1 - Math.sqrt(Math.max(0, 1 - Math.pow(1 - x, 2))),
};
function resolveProfile(p) {
    var _a;
    if (typeof p === 'function')
        return p;
    return (_a = PROFILES[p]) !== null && _a !== void 0 ? _a : PROFILES['convexSquircle'];
}
// ─── 1-D displacement map ────────────────────────────────────────────────────
/**
 * Compute refraction displacement along one radius of the bezel via Snell's law.
 *
 * @returns Array of lateral displacement values (one per sample).
 */
function compute1D(glassThickness, bezelWidth, profile, refractiveIndex, samples = 128) {
    const sf = resolveProfile(profile);
    const e = 1 / refractiveIndex;
    const result = [];
    for (let i = 0; i < samples; i++) {
        const x = i / samples;
        const y = sf(x);
        const dx = x < 1 ? 0.0001 : -0.0001;
        const d = (sf(Math.max(0, Math.min(1, x + dx))) - y) / dx;
        const m = Math.sqrt(d * d + 1);
        const nx = -d / m;
        const ny = -1 / m;
        const dt = ny;
        const k = 1 - e * e * (1 - dt * dt);
        if (k < 0) {
            result.push(0);
        }
        else {
            const rfx = -(e * dt + Math.sqrt(k)) * nx;
            const rfy = e - (e * dt + Math.sqrt(k)) * ny;
            result.push(rfx * ((y * bezelWidth + glassThickness) / rfy));
        }
    }
    return result;
}
/** Maximum absolute value in a 1D map — the normalisation denominator. */
function maxDisp(map1D) {
    return Math.max(...map1D.map(Math.abs));
}
// ─── 2-D displacement map ────────────────────────────────────────────────────
function compute2D(w, h, radius, bezelWidth, md, map1D) {
    var _a;
    const img = new ImageData(w, h);
    for (let i = 0; i < img.data.length; i += 4) {
        img.data[i] = 128;
        img.data[i + 1] = 128;
        img.data[i + 3] = 255;
    }
    const rSq = radius * radius;
    const rp1Sq = (radius + 1) ** 2;
    const rmBwSq = Math.max(0, radius - bezelWidth) ** 2;
    const wB = w - radius * 2;
    const hB = h - radius * 2;
    for (let y1 = 0; y1 < h; y1++) {
        for (let x1 = 0; x1 < w; x1++) {
            const idx = (y1 * w + x1) * 4;
            const x = x1 < radius ? x1 - radius : x1 >= w - radius ? x1 - radius - wB : 0;
            const y = y1 < radius ? y1 - radius : y1 >= h - radius ? y1 - radius - hB : 0;
            const dSq = x * x + y * y;
            if (dSq > rp1Sq || dSq < rmBwSq)
                continue;
            const dist = Math.sqrt(dSq);
            const op = dSq < rSq ? 1 : 1 - (dist - radius) / (Math.sqrt(rp1Sq) - radius);
            const t = Math.max(0, Math.min(1, (radius - dist) / bezelWidth));
            const bIdx = Math.min(Math.floor(t * map1D.length), map1D.length - 1);
            const dVal = (_a = map1D[Math.max(0, bIdx)]) !== null && _a !== void 0 ? _a : 0;
            const dX = md > 0 ? (-(dist > 0 ? x / dist : 0) * dVal) / md : 0;
            const dY = md > 0 ? (-(dist > 0 ? y / dist : 0) * dVal) / md : 0;
            img.data[idx] = Math.max(0, Math.min(255, 128 + dX * 127 * op));
            img.data[idx + 1] = Math.max(0, Math.min(255, 128 + dY * 127 * op));
        }
    }
    return img;
}
// ─── Specular highlight ───────────────────────────────────────────────────────
function computeSpecular(w, h, radius, _bezelWidth) {
    const img = new ImageData(w, h);
    const sVecX = Math.cos(Math.PI / 3);
    const sVecY = Math.sin(Math.PI / 3);
    const rSq = radius * radius;
    const rp1Sq = (radius + 1) ** 2;
    const rmSSq = Math.max(0, (radius - 1.5) ** 2);
    const wB = w - radius * 2;
    const hB = h - radius * 2;
    for (let y1 = 0; y1 < h; y1++) {
        for (let x1 = 0; x1 < w; x1++) {
            const x = x1 < radius ? x1 - radius : x1 >= w - radius ? x1 - radius - wB : 0;
            const y = y1 < radius ? y1 - radius : y1 >= h - radius ? y1 - radius - hB : 0;
            const dSq = x * x + y * y;
            if (dSq > rp1Sq || dSq < rmSSq)
                continue;
            const dist = Math.sqrt(dSq);
            const op = dSq < rSq ? 1 : 1 - (dist - radius) / (Math.sqrt(rp1Sq) - radius);
            const nx = dist > 0 ? x / dist : 0;
            const ny = dist > 0 ? y / dist : 0;
            const dp = Math.abs(nx * sVecX + -ny * sVecY);
            const t = Math.max(0, Math.min(1, (radius - dist) / 1.5));
            const cf = dp * Math.sqrt(1 - (1 - t) ** 2);
            const c = Math.min(255, 255 * cf);
            const idx = (y1 * w + x1) * 4;
            img.data[idx] = c;
            img.data[idx + 1] = c;
            img.data[idx + 2] = c;
            img.data[idx + 3] = Math.min(255, c * cf * op);
        }
    }
    return img;
}
// ─── Utility ─────────────────────────────────────────────────────────────────
function imageDataToURL(imageData) {
    const canvas = document.createElement('canvas');
    canvas.width = imageData.width;
    canvas.height = imageData.height;
    canvas.getContext('2d').putImageData(imageData, 0, 0);
    return canvas.toDataURL();
}
/** Convenience: run the full pipeline and return data URLs. */
function buildMaps(cfg) {
    var _a;
    const { width, height, radius, bezelWidth, glassThickness, refractiveIndex } = cfg;
    const profile = (_a = cfg.profile) !== null && _a !== void 0 ? _a : 'convexSquircle';
    const map1D = compute1D(glassThickness, bezelWidth, profile, refractiveIndex);
    const md = maxDisp(map1D);
    return {
        dispUrl: imageDataToURL(compute2D(width, height, radius, bezelWidth, md || 1, map1D)),
        specUrl: imageDataToURL(computeSpecular(width, height, radius)),
        maxDisplacement: md,
    };
}

const SVG_NS = 'http://www.w3.org/2000/svg';
const XLINK_NS = 'http://www.w3.org/1999/xlink';
let _uid = 0;
function nextFilterId(prefix = 'lg') {
    return `${prefix}-${++_uid}`;
}
// ─── Feature detection ───────────────────────────────────────────────────────
let _supported = null;
function supportsBackdropFilter() {
    if (_supported !== null)
        return _supported;
    const t = document.createElement('div');
    t.style.backdropFilter = 'url(#test)';
    _supported =
        !!window.chrome && t.style.backdropFilter.includes('url');
    return _supported;
}
// ─── SVG helpers ─────────────────────────────────────────────────────────────
function svgEl(tag, attrs = {}) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs))
        node.setAttribute(k, String(v));
    return node;
}
function feImg(id, w, h, result) {
    const node = svgEl('feImage', {
        id,
        x: 0,
        y: 0,
        width: w,
        height: h,
        result,
        preserveAspectRatio: 'none',
    });
    node.setAttribute('href', '');
    return node;
}
function setHref(node, url) {
    node.setAttributeNS(XLINK_NS, 'xlink:href', url);
    node.setAttribute('href', url);
}
// ─── Filter builder ───────────────────────────────────────────────────────────
function createFilterSVG(cfg) {
    const { filterId, width, height, blur = 0.5, scale = 25, saturation = 1.3, specularSlope = 0.8, filterMode = 'screen', } = cfg;
    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.style.cssText = 'width:0;height:0;position:absolute;overflow:hidden;';
    svg.setAttribute('aria-hidden', 'true');
    const defs = document.createElementNS(SVG_NS, 'defs');
    const filter = svgEl('filter', {
        id: filterId,
        x: '-50%',
        y: '-50%',
        width: '200%',
        height: '200%',
        'color-interpolation-filters': 'sRGB',
    });
    // 1 — pre-displacement blur
    const blurEl = svgEl('feGaussianBlur', {
        in: 'SourceGraphic',
        stdDeviation: blur,
        result: 'blurred',
    });
    filter.appendChild(blurEl);
    // 2 — displacement map image
    const dispImgEl = feImg(`${filterId}-di`, width, height, 'displacement_map');
    filter.appendChild(dispImgEl);
    // 3 — displacement
    const dispMapEl = svgEl('feDisplacementMap', {
        in: 'blurred',
        in2: 'displacement_map',
        scale,
        xChannelSelector: 'R',
        yChannelSelector: 'G',
        result: 'displaced',
    });
    filter.appendChild(dispMapEl);
    // 4 — saturation
    const satEl = svgEl('feColorMatrix', {
        in: 'displaced',
        type: 'saturate',
        values: saturation,
        result: 'displaced_saturated',
    });
    filter.appendChild(satEl);
    // 5 — specular image
    const specImgEl = feImg(`${filterId}-si`, width, height, 'specular_layer');
    filter.appendChild(specImgEl);
    if (filterMode === 'composite') {
        filter.appendChild(svgEl('feComposite', {
            in: 'displaced_saturated',
            in2: 'specular_layer',
            operator: 'in',
            result: 'specular_saturated',
        }));
        const tr = svgEl('feComponentTransfer', { in: 'specular_layer', result: 'specular_faded' });
        const fa = svgEl('feFuncA', { type: 'linear', slope: specularSlope });
        tr.appendChild(fa);
        filter.appendChild(tr);
        filter.appendChild(svgEl('feBlend', {
            in: 'specular_saturated',
            in2: 'displaced',
            mode: 'normal',
            result: 'withSaturation',
        }));
        filter.appendChild(svgEl('feBlend', {
            in: 'specular_faded',
            in2: 'withSaturation',
            mode: 'normal',
        }));
    }
    else {
        const tr = svgEl('feComponentTransfer', { in: 'specular_layer', result: 'specular_faded' });
        tr.appendChild(svgEl('feFuncA', { type: 'linear', slope: specularSlope }));
        filter.appendChild(tr);
        filter.appendChild(svgEl('feBlend', {
            in: 'specular_faded',
            in2: 'displaced_saturated',
            mode: 'screen',
        }));
    }
    defs.appendChild(filter);
    svg.appendChild(defs);
    const refs = { dispImgEl, specImgEl, dispMapEl, blurEl, satEl };
    return { svg, refs };
}
function injectImages(refs, dispUrl, specUrl) {
    setHref(refs.dispImgEl, dispUrl);
    setHref(refs.specImgEl, specUrl);
}
function setScale(refs, scale) {
    refs.dispMapEl.setAttribute('scale', String(scale));
}

// ─── Defaults ────────────────────────────────────────────────────────────────
const DEFAULTS = {
    width: 0, // 0 = auto-detect from element
    height: 0,
    radius: null,
    bezelWidth: 20,
    glassThickness: 80,
    refractiveIndex: 1.5,
    profile: 'convexSquircle',
    blur: 0.5,
    saturation: 1.3,
    specularSlope: 0.8,
    filterMode: 'screen',
};
// ─── Internal helpers ─────────────────────────────────────────────────────────
/** Resolve a selector or element, throwing if not found. Always returns Element. */
function resolveEl(target) {
    if (typeof target === 'string') {
        const found = document.querySelector(target);
        if (!found)
            throw new Error(`Liquid Glass: element not found — "${target}"`);
        return found;
    }
    if (target instanceof Element)
        return target;
    throw new Error(`Liquid Glass: invalid target — expected a CSS selector or Element`);
}
function readRadius(el, override) {
    if (override != null)
        return override;
    const r = parseFloat(getComputedStyle(el).borderTopLeftRadius);
    return Number.isFinite(r) ? r : 0;
}
// ─── Handle implementation ────────────────────────────────────────────────────
class LiquidGlassHandleImpl extends EventEmitter {
    constructor(element, setScaleFn, getMaxDispFn, cleanupFn, rebuildFn) {
        super();
        this.element = element;
        this._setScale = setScaleFn;
        this._getMaxDisp = getMaxDispFn;
        this._cleanup = cleanupFn;
        this._rebuild = rebuildFn;
    }
    refresh() {
        this._rebuild();
        return this;
    }
    destroy() {
        this._cleanup();
        this._emit('destroy');
    }
}
// ─── DOM injection ────────────────────────────────────────────────────────────
function inject(el, filterId, useBackdrop) {
    if (getComputedStyle(el).position === 'static') {
        el.style.position = 'relative';
    }
    const clone = document.createElement('div');
    clone.className = 'lg-clone';
    const cloneWorld = document.createElement('div');
    cloneWorld.className = 'lg-clone-world';
    clone.appendChild(cloneWorld);
    const inner = document.createElement('div');
    inner.className = 'lg-inner';
    el.insertBefore(inner, el.firstChild);
    el.insertBefore(clone, el.firstChild);
    if (useBackdrop) {
        clone.style.display = 'none';
        inner.style.backdropFilter = `url("#${filterId}")`;
        inner.style.webkitBackdropFilter =
            `url("#${filterId}")`;
    }
    else {
        // Non-Chrome fallback: CSS backdrop-filter (no displacement physics, but frosted glass).
        // Firefox and Safari both support blur()/saturate() in backdrop-filter.
        clone.style.display = 'none';
        const cssFilter = 'blur(8px) saturate(1.4) brightness(1.05)';
        inner.style.backdropFilter = cssFilter;
        inner.style.webkitBackdropFilter =
            cssFilter;
    }
    return { inner, clone };
}
// ─── Public factory ───────────────────────────────────────────────────────────
function createLiquidGlass(target, options = {}) {
    const el = resolveEl(target); // throws if not found
    const opts = Object.assign(Object.assign({}, DEFAULTS), options);
    const useBackdrop = supportsBackdropFilter();
    const filterId = nextFilterId();
    const getSize = () => ({
        w: opts.width || 0 || el.clientWidth || 100,
        h: opts.height || 0 || el.clientHeight || 100,
        r: readRadius(el, opts.radius),
    });
    const { w, h, r } = getSize();
    const initial = buildMaps({
        width: w,
        height: h,
        radius: r,
        bezelWidth: opts.bezelWidth,
        glassThickness: opts.glassThickness,
        refractiveIndex: opts.refractiveIndex,
        profile: opts.profile,
    });
    const { svg, refs } = createFilterSVG({
        filterId,
        width: w,
        height: h,
        blur: opts.blur,
        scale: initial.maxDisplacement,
        saturation: opts.saturation,
        specularSlope: opts.specularSlope,
        filterMode: opts.filterMode,
    });
    injectImages(refs, initial.dispUrl, initial.specUrl);
    el.appendChild(svg);
    inject(el, filterId, useBackdrop);
    let currentMaxDisp = initial.maxDisplacement;
    function rebuild() {
        const { w: w2, h: h2, r: r2 } = getSize();
        const maps = buildMaps({
            width: w2,
            height: h2,
            radius: r2,
            bezelWidth: opts.bezelWidth,
            glassThickness: opts.glassThickness,
            refractiveIndex: opts.refractiveIndex,
            profile: opts.profile,
        });
        // Update feImage dimensions so the displacement/specular maps cover the full element.
        refs.dispImgEl.setAttribute('width', String(w2));
        refs.dispImgEl.setAttribute('height', String(h2));
        refs.specImgEl.setAttribute('width', String(w2));
        refs.specImgEl.setAttribute('height', String(h2));
        injectImages(refs, maps.dispUrl, maps.specUrl);
        currentMaxDisp = maps.maxDisplacement;
        refs.dispMapEl.setAttribute('scale', String(currentMaxDisp));
        handle._emit('resize', { width: w2, height: h2 });
    }
    let ro = null;
    if (typeof ResizeObserver !== 'undefined') {
        ro = new ResizeObserver(rebuild);
        ro.observe(el);
    }
    const handle = new LiquidGlassHandleImpl(el, (s) => setScale(refs, s), () => currentMaxDisp, () => {
        var _a, _b;
        if (ro)
            ro.disconnect();
        svg.remove();
        (_a = el.querySelector('.lg-inner')) === null || _a === void 0 ? void 0 : _a.remove();
        (_b = el.querySelector('.lg-clone')) === null || _b === void 0 ? void 0 : _b.remove();
    }, rebuild);
    return handle;
}

/******************************************************************************
Copyright (c) Microsoft Corporation.

Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
PERFORMANCE OF THIS SOFTWARE.
***************************************************************************** */

function __rest(s, e) {
    var t = {};
    for (var p in s) if (Object.prototype.hasOwnProperty.call(s, p) && e.indexOf(p) < 0)
        t[p] = s[p];
    if (s != null && typeof Object.getOwnPropertySymbols === "function")
        for (var i = 0, p = Object.getOwnPropertySymbols(s); i < p.length; i++) {
            if (e.indexOf(p[i]) < 0 && Object.prototype.propertyIsEnumerable.call(s, p[i]))
                t[p[i]] = s[p[i]];
        }
    return t;
}

typeof SuppressedError === "function" ? SuppressedError : function (error, suppressed, message) {
    var e = new Error(message);
    return e.name = "SuppressedError", e.error = error, e.suppressed = suppressed, e;
};

/**
 * Damped spring physics — drives all animations in the liquid-glass
 * components (scale, position, opacity, displacement scale, etc.).
 */
class Spring {
    constructor(value, stiffness = 300, damping = 20) {
        this.value = value;
        this.target = value;
        this.velocity = 0;
        this.stiffness = stiffness;
        this.damping = damping;
    }
    setTarget(t) {
        this.target = t;
    }
    update(dt) {
        const force = (this.target - this.value) * this.stiffness;
        const drag = this.velocity * this.damping;
        this.velocity += (force - drag) * dt;
        this.value += this.velocity * dt;
        return this.value;
    }
    isSettled() {
        return Math.abs(this.target - this.value) < 0.001 && Math.abs(this.velocity) < 0.001;
    }
}

const DT = 1 / 60;
// ─── DOM event-listener tracker (auto-cleanup) ───────────────────────────────
function makeCleanupTracker() {
    const teardowns = [];
    function add(target, event, fn, opts) {
        target.addEventListener(event, fn, opts);
        teardowns.push(() => target.removeEventListener(event, fn, opts));
    }
    return { add, runAll: () => teardowns.forEach((fn) => fn()) };
}
// ─────────────────────────────────────────────────────────────────────────────
// Liquid Button
// ─────────────────────────────────────────────────────────────────────────────
class LiquidButtonHandleImpl extends EventEmitter {
    constructor(element, labelSpan, cleanup) {
        super();
        this.element = element;
        this._labelSpan = labelSpan;
        this._cleanup = cleanup;
    }
    setLabel(text) {
        this._labelSpan.textContent = text;
        return this;
    }
    destroy() {
        this._cleanup();
        this._emit('destroy');
    }
}
function createLiquidButton(target, options = {}) {
    const el = resolveEl(target);
    const { label } = options, glassOpts = __rest(options, ["label"]);
    el.classList.add('lg-button');
    if (!el.hasAttribute('type') && el.tagName === 'BUTTON')
        el.setAttribute('type', 'button');
    let labelSpan = el.querySelector('.lg-button-text');
    if (!labelSpan) {
        labelSpan = document.createElement('span');
        labelSpan.className = 'lg-button-text';
        el.appendChild(labelSpan);
    }
    if (label != null)
        labelSpan.textContent = label;
    const glass = createLiquidGlass(el, Object.assign({ bezelWidth: 26, glassThickness: 120, refractiveIndex: 2.0, blur: 0.8, saturation: 1.2, specularSlope: 0.8 }, glassOpts));
    const sp = {
        sc: new Spring(1, 400, 20),
        sd: new Spring(8, 400, 20),
        rs: new Spring(0.8, 300, 20),
    };
    let hover = false, pressed = false, af = null;
    function loop() {
        sp.sc.setTarget(pressed ? 0.9 : hover ? 1.05 : 1);
        sp.sd.setTarget(pressed ? 2 : hover ? 16 : 8);
        sp.rs.setTarget(pressed ? 1.5 : hover ? 1.2 : 0.8);
        const sc = sp.sc.update(DT), sd = sp.sd.update(DT), rs = sp.rs.update(DT);
        el.style.transform = `scale(${sc})`;
        glass._setScale(glass._getMaxDisp() * rs);
        const inner = el.querySelector('.lg-inner');
        if (inner)
            inner.style.boxShadow =
                `0 ${sd}px ${sd * 3}px rgba(0,0,0,.4),` +
                    `inset 0 2px 4px rgba(255,255,255,.2),` +
                    `inset 0 -2px 6px rgba(0,0,0,.4),` +
                    `inset 0 0 12px rgba(255,255,255,.1)`;
        if (!Object.values(sp).every((s) => s.isSettled()))
            af = requestAnimationFrame(loop);
        else
            af = null;
    }
    function kick() {
        if (!af)
            af = requestAnimationFrame(loop);
    }
    const ev = makeCleanupTracker();
    const handle = new LiquidButtonHandleImpl(el, labelSpan, () => {
        if (af !== null)
            cancelAnimationFrame(af);
        glass.destroy();
        ev.runAll();
        el.classList.remove('lg-button');
    });
    ev.add(el, 'click', (e) => handle._emit('click', e));
    ev.add(el, 'mouseenter', (e) => {
        hover = true;
        handle._emit('mouseenter', e);
        kick();
    });
    ev.add(el, 'mouseleave', (e) => {
        hover = false;
        pressed = false;
        handle._emit('mouseleave', e);
        kick();
    });
    ev.add(el, 'mousedown', (e) => {
        pressed = true;
        handle._emit('mousedown', e);
        kick();
    });
    ev.add(el, 'mouseup', (e) => {
        pressed = false;
        handle._emit('mouseup', e);
        kick();
    });
    ev.add(el, 'touchstart', () => {
        pressed = true;
        kick();
    }, { passive: false });
    ev.add(el, 'touchend', () => {
        pressed = false;
        kick();
    });
    af = requestAnimationFrame(loop);
    return handle;
}
// ─────────────────────────────────────────────────────────────────────────────
// Liquid Switch
// ─────────────────────────────────────────────────────────────────────────────
class LiquidSwitchHandleImpl extends EventEmitter {
    constructor(element, state, setChecked, cleanup) {
        super();
        this.element = element;
        this._state = state;
        this._setChecked = setChecked;
        this._cleanup = cleanup;
    }
    get checked() {
        return this._state.chk;
    }
    set checked(v) {
        this._setChecked(!!v, false);
    }
    toggle() {
        this._setChecked(!this._state.chk, true);
        return this;
    }
    destroy() {
        this._cleanup();
        this._emit('destroy');
    }
}
function createLiquidSwitch(target, options = {}) {
    const el = resolveEl(target);
    const { checked: initialChecked = false } = options, glassOpts = __rest(options, ["checked"]);
    const TW = 160, TH = 67, W = 146, H = 92, R = 46, BW = 19;
    const SR = 0.65, SA = 0.9;
    const ro = ((1 - SR) * W) / 2;
    const tr = TW - TH - (W - H) * SR;
    const track = document.createElement('div');
    track.className = 'lg-switch-track';
    const thumb = document.createElement('div');
    thumb.className = 'lg-switch-thumb';
    track.appendChild(thumb);
    el.appendChild(track);
    const glass = createLiquidGlass(thumb, Object.assign({ width: W, height: H, radius: R, bezelWidth: BW, glassThickness: 47, refractiveIndex: 1.5, blur: 0.2, saturation: 6, specularSlope: 0.5, filterMode: 'composite' }, glassOpts));
    const state = { chk: !!initialChecked, pd: false, ix: 0, xr: initialChecked ? 1 : 0 };
    const sp = {
        xr: new Spring(state.chk ? 1 : 0, 1000, 80),
        sc: new Spring(SR, 2000, 80),
        bo: new Spring(1, 2000, 80),
        tc: new Spring(state.chk ? 1 : 0, 1000, 80),
        sr: new Spring(0.4, 100, 10),
    };
    let af = null;
    const useBackdrop = supportsBackdropFilter();
    function loop() {
        if (!state.pd)
            sp.xr.setTarget(state.chk ? 1 : 0);
        sp.sc.setTarget(state.pd ? SA : SR);
        sp.bo.setTarget(state.pd ? 0.1 : 1);
        sp.sr.setTarget(state.pd ? 0.9 : 0.4);
        sp.tc.setTarget(state.pd ? (state.xr > 0.5 ? 1 : 0) : state.chk ? 1 : 0);
        const xr = sp.xr.update(DT), sc = sp.sc.update(DT), bo = sp.bo.update(DT), tc = sp.tc.update(DT);
        thumb.style.left = -ro + (TH - H * SR) / 2 + xr * tr + 'px';
        thumb.style.transform = `translateY(-50%) scale(${sc})`;
        thumb.style.backgroundColor = `rgba(255,255,255,${bo})`;
        thumb.style.boxShadow = state.pd
            ? '0 4px 22px rgba(0,0,0,.1),inset 2px 7px 24px rgba(0,0,0,.09)'
            : '0 10px 30px rgba(0,0,0,.5)';
        const r2 = Math.round(255 + (139 - 255) * tc);
        const g2 = Math.round(255 + (92 - 255) * tc);
        const b2 = Math.round(255 + (246 - 255) * tc);
        track.style.backgroundColor = `rgba(${r2},${g2},${b2},${0.05 + 0.45 * tc})`;
        const cloneEl = thumb.querySelector('.lg-clone');
        if (cloneEl && !useBackdrop)
            cloneEl.style.opacity = String(1 - bo);
        glass._setScale(glass._getMaxDisp() * sp.sr.update(DT));
        if (!Object.values(sp).every((s) => s.isSettled()))
            af = requestAnimationFrame(loop);
        else
            af = null;
    }
    function kick() {
        if (!af)
            af = requestAnimationFrame(loop);
    }
    function setChecked(v, emit) {
        state.chk = v;
        if (emit)
            handle._emit('change', { checked: state.chk, element: el });
        kick();
    }
    const ev = makeCleanupTracker();
    const handle = new LiquidSwitchHandleImpl(el, state, setChecked, () => {
        if (af !== null)
            cancelAnimationFrame(af);
        glass.destroy();
        ev.runAll();
    });
    ev.add(thumb, 'mousedown', (e) => {
        state.pd = true;
        state.ix = e.clientX;
        state.xr = state.chk ? 1 : 0;
        kick();
    });
    ev.add(thumb, 'touchstart', (e) => {
        e.preventDefault();
        state.pd = true;
        state.ix = e.touches[0].clientX;
        state.xr = state.chk ? 1 : 0;
        kick();
    }, { passive: false });
    ev.add(window, 'mousemove', (e) => {
        if (!state.pd)
            return;
        const cx = e.clientX;
        const rv = (state.chk ? 1 : 0) + (cx - state.ix) / tr;
        state.xr =
            Math.min(1, Math.max(0, rv)) +
                ((rv < 0 ? 1 : -1) * (rv < 0 ? -rv : rv > 1 ? rv - 1 : 0)) / 22;
        sp.xr.setTarget(state.xr);
        kick();
    });
    ev.add(window, 'touchmove', (e) => {
        if (!state.pd)
            return;
        e.preventDefault();
        const cx = e.touches[0].clientX;
        const rv = (state.chk ? 1 : 0) + (cx - state.ix) / tr;
        state.xr =
            Math.min(1, Math.max(0, rv)) +
                ((rv < 0 ? 1 : -1) * (rv < 0 ? -rv : rv > 1 ? rv - 1 : 0)) / 22;
        sp.xr.setTarget(state.xr);
        kick();
    }, { passive: false });
    ev.add(window, 'mouseup', (e) => {
        if (!state.pd)
            return;
        state.pd = false;
        const cx = e.clientX;
        const next = Math.abs(cx - state.ix) < 4 ? !state.chk : state.xr > 0.5;
        if (next !== state.chk)
            setChecked(next, true);
        else
            kick();
    });
    ev.add(window, 'touchend', (e) => {
        if (!state.pd)
            return;
        state.pd = false;
        const cx = e.changedTouches[0].clientX;
        const next = Math.abs(cx - state.ix) < 4 ? !state.chk : state.xr > 0.5;
        if (next !== state.chk)
            setChecked(next, true);
        else
            kick();
    });
    ev.add(track, 'click', (e) => {
        if (e.target === track)
            setChecked(!state.chk, true);
    });
    af = requestAnimationFrame(loop);
    return handle;
}
// ─────────────────────────────────────────────────────────────────────────────
// Liquid Slider
// ─────────────────────────────────────────────────────────────────────────────
class LiquidSliderHandleImpl extends EventEmitter {
    constructor(element, initial, setVal, cleanup) {
        super();
        this.element = element;
        this._current = initial;
        this._setVal = setVal;
        this._cleanup = cleanup;
    }
    get value() {
        return this._current;
    }
    set value(v) {
        this._setVal(v);
    }
    /** @internal */ _updateCurrent(v) {
        this._current = v;
    }
    destroy() {
        this._cleanup();
        this._emit('destroy');
    }
}
function createLiquidSlider(target, options = {}) {
    const el = resolveEl(target);
    const { min = 0, max = 100, value: initial = 50, step = 1 } = options, glassOpts = __rest(options, ["min", "max", "value", "step"]);
    const TW = 330, W = 90, H = 60, R = 30, BW = 16;
    const SR = 0.6;
    el.classList.add('lg-slider');
    const track = document.createElement('div');
    track.className = 'lg-slider-track';
    const fill = document.createElement('div');
    fill.className = 'lg-slider-fill';
    track.appendChild(fill);
    const thumb = document.createElement('div');
    thumb.className = 'lg-slider-thumb';
    el.appendChild(track);
    el.appendChild(thumb);
    const glass = createLiquidGlass(thumb, Object.assign({ width: W, height: H, radius: R, bezelWidth: BW, glassThickness: 80, refractiveIndex: 1.45, blur: 0, saturation: 7, specularSlope: 0.4, filterMode: 'composite' }, glassOpts));
    function clampStep(v) {
        return Math.min(max, Math.max(min, Math.round((v - min) / step) * step + min));
    }
    let current = clampStep(initial);
    let dragging = false;
    const sp = {
        sc: new Spring(SR, 2000, 80),
        bo: new Spring(1, 2000, 80),
        sr: new Spring(0.4, 100, 10),
    };
    let af = null;
    const useBackdrop = supportsBackdropFilter();
    function layout() {
        const pct = (current - min) / (max - min);
        fill.style.width = pct * 100 + '%';
        thumb.style.left = (W * SR) / 2 + pct * (TW - W * SR) - W / 2 + 'px';
    }
    function loop() {
        sp.sc.setTarget(dragging ? 1.0 : SR);
        sp.bo.setTarget(dragging ? 0.1 : 1);
        sp.sr.setTarget(dragging ? 0.9 : 0.4);
        const sc = sp.sc.update(DT), bo = sp.bo.update(DT);
        thumb.style.transform = `scale(${sc})`;
        thumb.style.backgroundColor = `rgba(255,255,255,${bo})`;
        const cloneEl = thumb.querySelector('.lg-clone');
        if (cloneEl && !useBackdrop)
            cloneEl.style.opacity = String(1 - bo);
        glass._setScale(glass._getMaxDisp() * sp.sr.update(DT));
        if (!Object.values(sp).every((s) => s.isSettled()))
            af = requestAnimationFrame(loop);
        else
            af = null;
    }
    function kick() {
        if (!af)
            af = requestAnimationFrame(loop);
    }
    function fromClientX(clientX) {
        const rect = track.getBoundingClientRect();
        const halfW = (W * SR) / 2;
        const pct = Math.min(1, Math.max(0, (clientX - rect.left - halfW) / (TW - W * SR)));
        const next = clampStep(min + pct * (max - min));
        if (next !== current) {
            current = next;
            handle._updateCurrent(current);
            layout();
            handle._emit('input', { value: current, element: el });
        }
    }
    const ev = makeCleanupTracker();
    const handle = new LiquidSliderHandleImpl(el, current, (v) => {
        current = clampStep(v);
        handle._updateCurrent(current);
        layout();
    }, () => {
        if (af !== null)
            cancelAnimationFrame(af);
        glass.destroy();
        ev.runAll();
        el.classList.remove('lg-slider');
    });
    ev.add(thumb, 'pointerdown', (e) => {
        e.preventDefault();
        dragging = true;
        thumb.setPointerCapture(e.pointerId);
        kick();
    });
    ev.add(window, 'pointermove', (e) => {
        if (dragging)
            fromClientX(e.clientX);
    });
    ev.add(window, 'pointerup', () => {
        if (!dragging)
            return;
        dragging = false;
        handle._emit('change', { value: current, element: el });
        kick();
    });
    layout();
    af = requestAnimationFrame(loop);
    return handle;
}
// ─────────────────────────────────────────────────────────────────────────────
// Liquid Cursor
// ─────────────────────────────────────────────────────────────────────────────
class LiquidCursorHandleImpl extends EventEmitter {
    constructor(element, cleanup) {
        super();
        this.element = element;
        this._cleanup = cleanup;
    }
    destroy() {
        this._cleanup();
        this._emit('destroy');
    }
}
/**
 * Glass orb that follows the mouse inside a container.
 * @param container  Element to track mouse events on.
 */
function createLiquidCursor(container, options = {}) {
    const cont = resolveEl(container);
    const { size = 90 } = options, glassOpts = __rest(options, ["size"]);
    if (getComputedStyle(cont).position === 'static')
        cont.style.position = 'relative';
    cont.style.cursor = 'none';
    const cursor = document.createElement('div');
    cursor.className = 'lg-cursor';
    cursor.style.width = size + 'px';
    cursor.style.height = size + 'px';
    cont.appendChild(cursor);
    const glass = createLiquidGlass(cursor, Object.assign({ width: size, height: size, radius: size / 2, bezelWidth: 15, glassThickness: 60, refractiveIndex: 1.45, blur: 0.5, saturation: 1.4, specularSlope: 0.8 }, glassOpts));
    const sp = {
        x: new Spring(0, 400, 25),
        y: new Spring(0, 400, 25),
        sc: new Spring(1, 350, 20),
    };
    let mx = 0, my = 0, inside = false, pressed = false, hovering = false, af = null;
    function loop() {
        sp.x.setTarget(mx);
        sp.y.setTarget(my);
        sp.sc.setTarget(pressed ? 0.7 : hovering ? 1.6 : 1.0);
        const cx = sp.x.update(DT), cy = sp.y.update(DT), cs = sp.sc.update(DT);
        const ox = cx - size / 2, oy = cy - size / 2;
        cursor.style.transform = `translate(${ox}px,${oy}px) scale(${cs})`;
        glass._setScale(glass._getMaxDisp() * cs);
        if (inside && !Object.values(sp).every((s) => s.isSettled()))
            af = requestAnimationFrame(loop);
        else
            af = null;
    }
    function kick() {
        if (!af)
            af = requestAnimationFrame(loop);
    }
    const ev = makeCleanupTracker();
    ev.add(cont, 'mousemove', (e) => {
        const r = cont.getBoundingClientRect();
        mx = e.clientX - r.left;
        my = e.clientY - r.top;
        if (!inside) {
            inside = true;
            cursor.classList.add('lg-cursor-visible');
            sp.x.value = mx;
            sp.y.value = my;
        }
        kick();
    });
    ev.add(cont, 'mouseleave', () => {
        inside = false;
        cursor.classList.remove('lg-cursor-visible');
    });
    ev.add(cont, 'mousedown', () => {
        pressed = true;
        kick();
    });
    ev.add(cont, 'mouseup', () => {
        pressed = false;
        kick();
    });
    ev.add(cont, 'mouseenter', () => {
        hovering = true;
        kick();
    });
    return new LiquidCursorHandleImpl(cursor, () => {
        if (af !== null)
            cancelAnimationFrame(af);
        glass.destroy();
        ev.runAll();
        cursor.remove();
        cont.style.cursor = '';
    });
}
// ─────────────────────────────────────────────────────────────────────────────
// Liquid Input
// ─────────────────────────────────────────────────────────────────────────────
class LiquidInputHandleImpl extends EventEmitter {
    constructor(element, input, cleanup) {
        super();
        this.element = element;
        this._input = input;
        this._cleanup = cleanup;
    }
    get value() {
        return this._input.value;
    }
    set value(v) {
        this._input.value = v;
    }
    focus() {
        this._input.focus();
        return this;
    }
    blur() {
        this._input.blur();
        return this;
    }
    destroy() {
        this._cleanup();
        this._emit('destroy');
    }
}
/**
 * Glass-wrapped text input with micro-vibration on typing.
 */
function createLiquidInput(target, options = {}) {
    const el = resolveEl(target);
    const { placeholder = '', value: initVal = '', type = 'text' } = options, glassOpts = __rest(options, ["placeholder", "value", "type"]);
    el.classList.add('lg-input-wrapper');
    const glass = createLiquidGlass(el, Object.assign({ width: 340, height: 60, radius: 30, bezelWidth: 15, glassThickness: 60, refractiveIndex: 1.5, blur: 0.5, saturation: 1.2, specularSlope: 0.7 }, glassOpts));
    const input = document.createElement('input');
    input.type = type;
    input.className = 'lg-input-field';
    input.placeholder = placeholder;
    input.value = initVal;
    el.appendChild(input);
    const sp = { sc: new Spring(1, 400, 20), sx: new Spring(1, 400, 25), sy: new Spring(1, 400, 25) };
    let af = null;
    function loop() {
        sp.sc.setTarget(1);
        sp.sx.setTarget(1);
        sp.sy.setTarget(1);
        const s = sp.sc.update(DT), sx = sp.sx.update(DT), sy = sp.sy.update(DT);
        el.style.transform = `scale(${s * sx}, ${s * sy})`;
        glass._setScale(glass._getMaxDisp() * s);
        if (!Object.values(sp).every((s) => s.isSettled()))
            af = requestAnimationFrame(loop);
        else
            af = null;
    }
    function kick() {
        if (!af)
            af = requestAnimationFrame(loop);
    }
    const handle = new LiquidInputHandleImpl(el, input, () => {
        if (af !== null)
            cancelAnimationFrame(af);
        glass.destroy();
        ev.runAll();
        input.remove();
        el.classList.remove('lg-input-wrapper');
    });
    const ev = makeCleanupTracker();
    ev.add(input, 'focus', (e) => {
        sp.sc.setTarget(1.05);
        kick();
        handle._emit('focus', e);
    });
    ev.add(input, 'blur', (e) => {
        sp.sc.setTarget(1.0);
        kick();
        handle._emit('blur', e);
    });
    ev.add(input, 'input', () => {
        sp.sx.velocity += 1.5;
        sp.sy.velocity -= 0.8;
        kick();
        handle._emit('input', { value: input.value, element: el });
    });
    return handle;
}
// ─────────────────────────────────────────────────────────────────────────────
// Liquid Dial
// ─────────────────────────────────────────────────────────────────────────────
class LiquidDialHandleImpl extends EventEmitter {
    constructor(element, initial, cleanup) {
        super();
        this.element = element;
        this._angle = initial;
        this._cleanup = cleanup;
    }
    get angle() {
        return this._angle;
    }
    set angle(v) {
        this._angle = v;
    }
    /** @internal */ _syncAngle(v) {
        this._angle = v;
    }
    destroy() {
        this._cleanup();
        this._emit('destroy');
    }
}
/**
 * Rotary knob — drag to spin, fires 'change' with the new angle.
 */
function createLiquidDial(target, options = {}) {
    const el = resolveEl(target);
    const { value: initAngle = 0 } = options, glassOpts = __rest(options, ["value"]);
    el.classList.add('lg-dial');
    const knob = document.createElement('div');
    knob.className = 'lg-dial-knob';
    const indicator = document.createElement('div');
    indicator.className = 'lg-dial-indicator';
    knob.appendChild(indicator);
    el.appendChild(knob);
    const glass = createLiquidGlass(knob, Object.assign({ width: 140, height: 140, radius: 70, bezelWidth: 20, glassThickness: 80, refractiveIndex: 1.8, blur: 0.5, saturation: 1.2, specularSlope: 0.9 }, glassOpts));
    let currentAngle = initAngle, lastRaw = 0, dragging = false;
    const sp = { angle: new Spring(initAngle, 400, 30), scale: new Spring(1, 400, 20) };
    let af = null;
    function loop() {
        sp.scale.setTarget(dragging ? 1.05 : 1);
        const a = sp.angle.update(DT), sc = sp.scale.update(DT);
        knob.style.transform = `scale(${sc}) rotate(${a}deg)`;
        glass._setScale(glass._getMaxDisp() * sc);
        if (!Object.values(sp).every((s) => s.isSettled()))
            af = requestAnimationFrame(loop);
        else
            af = null;
    }
    function kick() {
        if (!af)
            af = requestAnimationFrame(loop);
    }
    function angleFrom(e) {
        const r = el.getBoundingClientRect();
        return (Math.atan2(e.clientY - r.top - r.height / 2, e.clientX - r.left - r.width / 2) *
            (180 / Math.PI));
    }
    const handle = new LiquidDialHandleImpl(el, initAngle, () => {
        if (af !== null)
            cancelAnimationFrame(af);
        glass.destroy();
        ev.runAll();
        knob.remove();
        el.classList.remove('lg-dial');
    });
    const ev = makeCleanupTracker();
    ev.add(knob, 'pointerdown', (e) => {
        dragging = true;
        knob.setPointerCapture(e.pointerId);
        lastRaw = angleFrom(e);
        kick();
    });
    ev.add(knob, 'pointermove', (e) => {
        if (!dragging)
            return;
        const raw = angleFrom(e);
        let delta = raw - lastRaw;
        if (delta > 180)
            delta -= 360;
        if (delta < -180)
            delta += 360;
        currentAngle += delta;
        lastRaw = raw;
        sp.angle.setTarget(currentAngle);
        handle._syncAngle(currentAngle);
        handle._emit('change', { angle: currentAngle, element: el });
        kick();
    });
    ev.add(knob, 'pointerup', () => {
        dragging = false;
        kick();
    });
    af = requestAnimationFrame(loop);
    return handle;
}
// ─────────────────────────────────────────────────────────────────────────────
// Liquid Tooltip
// ─────────────────────────────────────────────────────────────────────────────
class LiquidTooltipHandleImpl extends EventEmitter {
    constructor(element, textEl, show, hide, cleanup) {
        super();
        this.element = element;
        this._textEl = textEl;
        this._show = show;
        this._hide = hide;
        this._cleanup = cleanup;
    }
    show() {
        this._show();
        return this;
    }
    hide() {
        this._hide();
        return this;
    }
    toggle() {
        return this;
    } // state tracked in closure
    setText(text) {
        this._textEl.textContent = text;
        return this;
    }
    destroy() {
        this._cleanup();
        this._emit('destroy');
    }
}
/**
 * Glass pill that springs into view above a trigger element on hover.
 */
function createLiquidTooltip(target, options) {
    const el = resolveEl(target);
    const trigger = resolveEl(options.trigger);
    const { text = '' } = options, glassOpts = __rest(options, ["text"]);
    el.classList.add('lg-tooltip');
    el.style.cssText +=
        ';position:absolute;bottom:calc(100% + 14px);left:50%;transform-origin:bottom center;';
    const textEl = el.querySelector('.lg-tooltip-text') ||
        (() => {
            const t = document.createElement('span');
            t.className = 'lg-tooltip-text';
            el.appendChild(t);
            return t;
        })();
    textEl.textContent = text;
    const glass = createLiquidGlass(el, Object.assign({ width: 140, height: 46, radius: 23, bezelWidth: 15, glassThickness: 60, refractiveIndex: 1.6, blur: 0.5, saturation: 1.2, specularSlope: 0.8 }, glassOpts));
    let visible = false;
    const sp = { sc: new Spring(0.5, 400, 25), y: new Spring(20, 400, 25) };
    let af = null;
    function loop() {
        const sc = sp.sc.update(DT), y = sp.y.update(DT);
        el.style.transform = `translateX(-50%) translateY(${y}px) scale(${sc})`;
        el.style.opacity = String(Math.max(0, (sc - 0.5) * 2));
        glass._setScale(glass._getMaxDisp() * sc);
        if (!Object.values(sp).every((s) => s.isSettled()))
            af = requestAnimationFrame(loop);
        else
            af = null;
    }
    function kick() {
        if (!af)
            af = requestAnimationFrame(loop);
    }
    function doShow() {
        sp.sc.setTarget(1);
        sp.y.setTarget(0);
        visible = true;
        kick();
        handle._emit('show');
    }
    function doHide() {
        sp.sc.setTarget(0.5);
        sp.y.setTarget(20);
        visible = false;
        kick();
        handle._emit('hide');
    }
    const handle = new LiquidTooltipHandleImpl(el, textEl, doShow, doHide, () => {
        if (af !== null)
            cancelAnimationFrame(af);
        glass.destroy();
        ev.runAll();
        el.classList.remove('lg-tooltip');
    });
    handle.toggle = function () {
        if (visible) {
            doHide();
        }
        else {
            doShow();
        }
        return this;
    };
    const ev = makeCleanupTracker();
    ev.add(trigger, 'mouseenter', doShow);
    ev.add(trigger, 'mouseleave', doHide);
    ev.add(trigger, 'focus', doShow);
    ev.add(trigger, 'blur', doHide);
    // Start hidden
    el.style.opacity = '0';
    el.style.transform = 'translateX(-50%) translateY(20px) scale(0.5)';
    af = requestAnimationFrame(loop);
    return handle;
}
// ─────────────────────────────────────────────────────────────────────────────
// Liquid Textarea
// ─────────────────────────────────────────────────────────────────────────────
class LiquidTextareaHandleImpl extends EventEmitter {
    constructor(element, ta, autoResize, cleanup) {
        super();
        this.element = element;
        this._ta = ta;
        this._autoResize = autoResize;
        this._cleanup = cleanup;
    }
    get value() {
        return this._ta.value;
    }
    set value(v) {
        this._ta.value = v;
        this._autoResize();
    }
    focus() {
        this._ta.focus();
        return this;
    }
    blur() {
        this._ta.blur();
        return this;
    }
    destroy() {
        this._cleanup();
        this._emit('destroy');
    }
}
/**
 * Glass-wrapped multi-line textarea with auto-resize and micro-vibration on typing.
 *
 * Uses the CSS grid replication trick: a hidden ::after ghost mirrors the textarea
 * content via data-replicated-value, driving the wrapper's height purely through CSS.
 * No scrollHeight measurement — works in all browsers regardless of positioning context.
 */
function createLiquidTextarea(target, options = {}) {
    const el = resolveEl(target);
    const { placeholder = '', value: initVal = '', rows = 4 } = options, glassOpts = __rest(options, ["placeholder", "value", "rows"]);
    el.classList.add('lg-textarea-wrapper');
    const minH = rows * 24 + 32;
    // min-height ensures the wrapper is never smaller than the requested row count,
    // even when the ghost ::after has less content.
    el.style.minHeight = minH + 'px';
    // Sync initial value to the ghost before appending the textarea so glass reads
    // the correct el.clientHeight on first measurement.
    el.dataset.replicatedValue = initVal;
    const ta = document.createElement('textarea');
    ta.className = 'lg-textarea-field';
    ta.placeholder = placeholder;
    ta.value = initVal;
    ta.rows = rows;
    el.appendChild(ta);
    // No explicit height — glass auto-detects from el.clientHeight (driven by CSS grid).
    const glass = createLiquidGlass(el, Object.assign({ width: 340, radius: 16, bezelWidth: 15, glassThickness: 60, refractiveIndex: 1.5, blur: 0.5, saturation: 1.2, specularSlope: 0.7 }, glassOpts));
    const sp = { sc: new Spring(1, 400, 20), sx: new Spring(1, 400, 25), sy: new Spring(1, 400, 25) };
    let af = null;
    function loop() {
        sp.sc.setTarget(1);
        sp.sx.setTarget(1);
        sp.sy.setTarget(1);
        const s = sp.sc.update(DT), sx = sp.sx.update(DT), sy = sp.sy.update(DT);
        el.style.transform = `scale(${s * sx}, ${s * sy})`;
        glass._setScale(glass._getMaxDisp() * s);
        if (!Object.values(sp).every((spr) => spr.isSettled()))
            af = requestAnimationFrame(loop);
        else
            af = null;
    }
    function kick() {
        if (!af)
            af = requestAnimationFrame(loop);
    }
    function autoResize() {
        // Reset ta to intrinsic height so scrollHeight measures true content, not
        // a previously-set value (scrollHeight >= clientHeight, so stale heights
        // would prevent the textarea from ever shrinking back down).
        ta.style.height = 'auto';
        // Reading scrollHeight forces a synchronous reflow with height:auto applied,
        // giving us the true content height even when content exceeds the rows attribute.
        const newH = Math.max(minH, ta.scrollHeight);
        // Grow the textarea so the user can see all typed content without scrolling.
        ta.style.height = newH + 'px';
        // Give el an explicit definite height so the absolutely-positioned glass layers
        // (.lg-inner, .lg-clone with inset:0) know how tall the containing block is.
        el.style.height = newH + 'px';
        // Keep ghost in sync (drives CSS grid as a fallback measurement aid).
        el.dataset.replicatedValue = ta.value;
    }
    const handle = new LiquidTextareaHandleImpl(el, ta, autoResize, () => {
        if (af !== null)
            cancelAnimationFrame(af);
        glass.destroy();
        ev.runAll();
        ta.remove();
        el.classList.remove('lg-textarea-wrapper');
        el.style.transform = '';
        el.style.minHeight = '';
        el.style.height = '';
        delete el.dataset.replicatedValue;
    });
    const ev = makeCleanupTracker();
    // Commit the initial height so glass layers have a definite containing-block height.
    autoResize();
    ev.add(ta, 'focus', (e) => {
        sp.sc.setTarget(1.02);
        kick();
        handle._emit('focus', e);
    });
    ev.add(ta, 'blur', (e) => {
        sp.sc.setTarget(1.0);
        kick();
        handle._emit('blur', e);
        handle._emit('change', { value: ta.value, element: el });
    });
    ev.add(ta, 'input', () => {
        sp.sx.velocity += 1.0;
        sp.sy.velocity -= 0.5;
        kick();
        autoResize();
        handle._emit('input', { value: ta.value, element: el });
    });
    return handle;
}
// ─────────────────────────────────────────────────────────────────────────────
// Liquid Select
// ─────────────────────────────────────────────────────────────────────────────
class LiquidSelectHandleImpl extends EventEmitter {
    constructor(element, native, labelEl, placeholder, initial, cleanup) {
        super();
        this.element = element;
        this._native = native;
        this._labelEl = labelEl;
        this._placeholder = placeholder;
        this._value = initial;
        this._cleanup = cleanup;
    }
    get value() {
        return this._value;
    }
    set value(v) {
        this._value = v;
        this._native.value = v;
        this._syncLabel();
    }
    _syncLabel() {
        const opt = Array.from(this._native.options).find((o) => o.value === this._value);
        if (opt && this._value !== '') {
            this._labelEl.textContent = opt.text;
            this._labelEl.classList.remove('lg-select-placeholder');
        }
        else {
            this._labelEl.textContent = this._placeholder;
            this._labelEl.classList.add('lg-select-placeholder');
        }
    }
    setOptions(opts) {
        while (this._native.options.length > 0)
            this._native.remove(0);
        const ph = document.createElement('option');
        ph.value = '';
        ph.text = this._placeholder;
        ph.disabled = true;
        ph.selected = !this._value;
        this._native.add(ph);
        opts.forEach((o) => {
            const opt = document.createElement('option');
            opt.value = o.value;
            opt.text = o.label;
            if (o.value === this._value)
                opt.selected = true;
            this._native.add(opt);
        });
        this._syncLabel();
        return this;
    }
    /** @internal */ _syncValue(v) {
        this._value = v;
    }
    destroy() {
        this._cleanup();
        this._emit('destroy');
    }
}
/**
 * Glass-wrapped native select with animated chevron and custom label display.
 */
function createLiquidSelect(target, options = {}) {
    const el = resolveEl(target);
    const { options: items = [], value: initVal = '', placeholder = 'Select…' } = options, glassOpts = __rest(options, ["options", "value", "placeholder"]);
    el.classList.add('lg-select-wrapper');
    const glass = createLiquidGlass(el, Object.assign({ width: 340, height: 60, radius: 30, bezelWidth: 15, glassThickness: 60, refractiveIndex: 1.5, blur: 0.5, saturation: 1.2, specularSlope: 0.7 }, glassOpts));
    const display = document.createElement('div');
    display.className = 'lg-select-display';
    const labelEl = document.createElement('span');
    labelEl.className = 'lg-select-label lg-select-placeholder';
    labelEl.textContent = placeholder;
    const chevron = document.createElement('span');
    chevron.className = 'lg-select-chevron';
    chevron.innerHTML =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" ' +
            'stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>';
    display.appendChild(labelEl);
    display.appendChild(chevron);
    el.appendChild(display);
    const native = document.createElement('select');
    native.className = 'lg-select-native';
    const phOpt = document.createElement('option');
    phOpt.value = '';
    phOpt.text = placeholder;
    phOpt.disabled = true;
    phOpt.selected = !initVal;
    native.add(phOpt);
    items.forEach((o) => {
        const opt = document.createElement('option');
        opt.value = o.value;
        opt.text = o.label;
        if (o.value === initVal)
            opt.selected = true;
        native.add(opt);
    });
    el.appendChild(native);
    if (initVal) {
        const found = items.find((o) => o.value === initVal);
        if (found) {
            labelEl.textContent = found.label;
            labelEl.classList.remove('lg-select-placeholder');
        }
    }
    const sp = { sc: new Spring(1, 400, 20), cv: new Spring(0, 300, 20) };
    let af = null;
    function loop() {
        sp.sc.setTarget(1);
        const s = sp.sc.update(DT), cv = sp.cv.update(DT);
        el.style.transform = `scale(${s})`;
        glass._setScale(glass._getMaxDisp() * s);
        chevron.style.transform = `rotate(${cv * 180}deg)`;
        if (!Object.values(sp).every((spr) => spr.isSettled()))
            af = requestAnimationFrame(loop);
        else
            af = null;
    }
    function kick() {
        if (!af)
            af = requestAnimationFrame(loop);
    }
    const handle = new LiquidSelectHandleImpl(el, native, labelEl, placeholder, initVal, () => {
        if (af !== null)
            cancelAnimationFrame(af);
        glass.destroy();
        ev.runAll();
        display.remove();
        native.remove();
        el.classList.remove('lg-select-wrapper');
        el.style.transform = '';
    });
    const ev = makeCleanupTracker();
    ev.add(native, 'focus', (e) => {
        sp.sc.setTarget(1.03);
        sp.cv.setTarget(1);
        kick();
        handle._emit('focus', e);
    });
    ev.add(native, 'blur', (e) => {
        sp.sc.setTarget(1.0);
        sp.cv.setTarget(0);
        kick();
        handle._emit('blur', e);
    });
    ev.add(native, 'change', () => {
        var _a;
        handle._syncValue(native.value);
        const opt = native.options[native.selectedIndex];
        if (opt && native.value !== '') {
            labelEl.textContent = opt.text;
            labelEl.classList.remove('lg-select-placeholder');
        }
        else {
            labelEl.textContent = placeholder;
            labelEl.classList.add('lg-select-placeholder');
        }
        sp.sc.velocity += 0.5;
        kick();
        handle._emit('change', { value: native.value, label: (_a = opt === null || opt === void 0 ? void 0 : opt.text) !== null && _a !== void 0 ? _a : '', element: el });
    });
    return handle;
}
// ─────────────────────────────────────────────────────────────────────────────
// Liquid Checkbox
// ─────────────────────────────────────────────────────────────────────────────
class LiquidCheckboxHandleImpl extends EventEmitter {
    constructor(element, state, setChecked, cleanup) {
        super();
        this.element = element;
        this._state = state;
        this._setChecked = setChecked;
        this._cleanup = cleanup;
    }
    get checked() {
        return this._state.chk;
    }
    set checked(v) {
        this._setChecked(!!v, false);
    }
    toggle() {
        this._setChecked(!this._state.chk, true);
        return this;
    }
    destroy() {
        this._cleanup();
        this._emit('destroy');
    }
}
/**
 * Glass-wrapped checkbox with spring-animated checkmark.
 */
function createLiquidCheckbox(target, options = {}) {
    const el = resolveEl(target);
    const { checked: initChecked = false, label = '' } = options, glassOpts = __rest(options, ["checked", "label"]);
    el.classList.add('lg-checkbox');
    el.setAttribute('role', 'checkbox');
    el.setAttribute('tabindex', '0');
    el.setAttribute('aria-checked', String(!!initChecked));
    const box = document.createElement('div');
    box.className = 'lg-checkbox-box';
    const checkEl = document.createElement('div');
    checkEl.className = 'lg-checkbox-check';
    checkEl.innerHTML =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" ' +
            'stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>';
    box.appendChild(checkEl);
    el.appendChild(box);
    if (label) {
        const labelEl = document.createElement('span');
        labelEl.className = 'lg-checkbox-label-text';
        labelEl.textContent = label;
        el.appendChild(labelEl);
    }
    const glass = createLiquidGlass(box, Object.assign({ width: 36, height: 36, radius: 10, bezelWidth: 8, glassThickness: 40, refractiveIndex: 1.6, blur: 0.3, saturation: 1.3, specularSlope: 0.8 }, glassOpts));
    const state = { chk: !!initChecked };
    const sp = {
        sc: new Spring(initChecked ? 1 : 0, 600, 30),
        box: new Spring(1, 400, 20),
    };
    let af = null;
    // Set initial visual state without waiting for the first frame
    checkEl.style.transform = `scale(${initChecked ? 1 : 0})`;
    checkEl.style.opacity = String(initChecked ? 1 : 0);
    function loop() {
        sp.sc.setTarget(state.chk ? 1 : 0);
        sp.box.setTarget(1);
        const sc = sp.sc.update(DT), bs = sp.box.update(DT);
        checkEl.style.transform = `scale(${sc})`;
        checkEl.style.opacity = String(Math.max(0, sc));
        box.style.transform = `scale(${bs})`;
        glass._setScale(glass._getMaxDisp() * bs);
        if (!Object.values(sp).every((spr) => spr.isSettled()))
            af = requestAnimationFrame(loop);
        else
            af = null;
    }
    function kick() {
        if (!af)
            af = requestAnimationFrame(loop);
    }
    function setChecked(v, emit) {
        state.chk = v;
        el.setAttribute('aria-checked', String(v));
        sp.box.velocity += 1.5;
        kick();
        if (emit)
            handle._emit('change', { checked: state.chk, element: el });
    }
    const handle = new LiquidCheckboxHandleImpl(el, state, setChecked, () => {
        if (af !== null)
            cancelAnimationFrame(af);
        glass.destroy();
        ev.runAll();
        box.remove();
        el.classList.remove('lg-checkbox');
        el.removeAttribute('role');
        el.removeAttribute('tabindex');
        el.removeAttribute('aria-checked');
    });
    const ev = makeCleanupTracker();
    ev.add(el, 'click', () => setChecked(!state.chk, true));
    ev.add(el, 'keydown', (e) => {
        const key = e.key;
        if (key === ' ' || key === 'Enter') {
            e.preventDefault();
            setChecked(!state.chk, true);
        }
    });
    af = requestAnimationFrame(loop);
    return handle;
}
// ─────────────────────────────────────────────────────────────────────────────
// Liquid Progress
// ─────────────────────────────────────────────────────────────────────────────
class LiquidProgressHandleImpl extends EventEmitter {
    constructor(element, initial, set, cleanup) {
        super();
        this.element = element;
        this._val = initial;
        this._set = set;
        this._cleanup = cleanup;
    }
    get value() {
        return this._val;
    }
    set value(v) {
        this._set(v);
    }
    /** @internal */ _syncVal(v) {
        this._val = v;
    }
    destroy() {
        this._cleanup();
        this._emit('destroy');
    }
}
/**
 * Glass-overlaid progress bar that squishes on value change.
 */
function createLiquidProgress(target, options = {}) {
    const el = resolveEl(target);
    const { value: initVal = 0 } = options, glassOpts = __rest(options, ["value"]);
    el.classList.add('lg-progress');
    const fill = document.createElement('div');
    fill.className = 'lg-progress-fill';
    el.appendChild(fill);
    const glass = createLiquidGlass(el, Object.assign({ bezelWidth: 12, glassThickness: 50, refractiveIndex: 1.5, blur: 0.5, saturation: 1.2, specularSlope: 0.7 }, glassOpts));
    let current = Math.min(100, Math.max(0, initVal));
    const sp = { progress: new Spring(current, 200, 25), sy: new Spring(1, 400, 20) };
    let af = null;
    function loop() {
        sp.sy.setTarget(1);
        const prog = sp.progress.update(DT), sy = sp.sy.update(DT);
        fill.style.width = `${Math.max(0, Math.min(100, prog))}%`;
        el.style.transform = `scaleY(${sy})`;
        glass._setScale(glass._getMaxDisp() * sy);
        if (!Object.values(sp).every((s) => s.isSettled()))
            af = requestAnimationFrame(loop);
        else
            af = null;
    }
    function kick() {
        if (!af)
            af = requestAnimationFrame(loop);
    }
    const handle = new LiquidProgressHandleImpl(el, current, (v) => {
        current = Math.min(100, Math.max(0, v));
        sp.progress.setTarget(current);
        sp.sy.velocity += 1.2;
        handle._syncVal(current);
        handle._emit('change', { value: current, element: el });
        kick();
    }, () => {
        if (af !== null)
            cancelAnimationFrame(af);
        glass.destroy();
        fill.remove();
        el.classList.remove('lg-progress');
    });
    af = requestAnimationFrame(loop);
    return handle;
}
// ─────────────────────────────────────────────────────────────────────────────
// Liquid Radio
// ─────────────────────────────────────────────────────────────────────────────
class LiquidRadioHandleImpl extends EventEmitter {
    constructor(element, value, setValue, setOptions, cleanup) {
        super();
        this.element = element;
        this._value = value;
        this._setValue = setValue;
        this._setOptions = setOptions;
        this._cleanup = cleanup;
    }
    get value() {
        return this._value;
    }
    set value(v) {
        this._setValue(v);
    }
    /** @internal */ _syncValue(v) {
        this._value = v;
    }
    setOptions(opts) {
        this._setOptions(opts);
        return this;
    }
    destroy() {
        this._cleanup();
        this._emit('destroy');
    }
}
/**
 * Glass radio-button group with spring-animated selection dot.
 */
function createLiquidRadio(target, options = {}) {
    const el = resolveEl(target);
    const { options: initOpts = [], value: initVal = '' } = options, glassOpts = __rest(options, ["options", "value"]);
    el.classList.add('lg-radio-group');
    let currentValue = initVal;
    let items = [];
    function destroyItems() {
        items.forEach(({ glass, ev: iev, af: iaf }) => {
            if (iaf !== null)
                cancelAnimationFrame(iaf);
            glass.destroy();
            iev.runAll();
        });
        items = [];
        el.querySelectorAll('.lg-radio-item').forEach((e) => e.remove());
    }
    function selectValue(v, emit = true) {
        currentValue = v;
        handle._syncValue(v);
        items.forEach((item) => {
            item.optEl.setAttribute('aria-checked', item.optValue === v ? 'true' : 'false');
            item.kick();
        });
        if (emit)
            handle._emit('change', { value: v, element: el });
    }
    function buildItems(opts) {
        destroyItems();
        opts.forEach((opt, i) => {
            const optEl = document.createElement('div');
            optEl.className = 'lg-radio-item';
            optEl.setAttribute('role', 'radio');
            optEl.setAttribute('tabindex', i === 0 ? '0' : '-1');
            optEl.setAttribute('aria-checked', opt.value === currentValue ? 'true' : 'false');
            optEl.dataset.value = opt.value;
            const circle = document.createElement('div');
            circle.className = 'lg-radio-circle';
            const dot = document.createElement('div');
            dot.className = 'lg-radio-dot';
            const dotInner = document.createElement('div');
            dotInner.className = 'lg-radio-dot-inner';
            dot.appendChild(dotInner);
            circle.appendChild(dot);
            const labelSpan = document.createElement('span');
            labelSpan.className = 'lg-radio-label-text';
            labelSpan.textContent = opt.label;
            optEl.appendChild(circle);
            optEl.appendChild(labelSpan);
            el.appendChild(optEl);
            const glass = createLiquidGlass(circle, Object.assign({ width: 28, height: 28, radius: 14, bezelWidth: 7, glassThickness: 40, refractiveIndex: 1.4, blur: 0.3, saturation: 1.1, specularSlope: 0.5 }, glassOpts));
            const isSelected = opt.value === currentValue;
            const sp = new Spring(isSelected ? 1 : 0, 500, 22);
            let iaf = null;
            dot.style.transform = `scale(${isSelected ? 1 : 0})`;
            dot.style.opacity = isSelected ? '1' : '0';
            function loop() {
                sp.setTarget(opt.value === currentValue ? 1 : 0);
                const v = sp.update(DT);
                dot.style.transform = `scale(${v})`;
                dot.style.opacity = String(Math.max(0, Math.min(1, v)));
                if (!sp.isSettled())
                    iaf = requestAnimationFrame(loop);
                else
                    iaf = null;
            }
            function kick() {
                if (!iaf)
                    iaf = requestAnimationFrame(loop);
            }
            const itemEv = makeCleanupTracker();
            itemEv.add(optEl, 'click', () => {
                if (currentValue !== opt.value)
                    selectValue(opt.value);
            });
            itemEv.add(optEl, 'keydown', (e) => {
                const ke = e;
                if (ke.key === ' ' || ke.key === 'Enter') {
                    ke.preventDefault();
                    if (currentValue !== opt.value)
                        selectValue(opt.value);
                }
                if (ke.key === 'ArrowDown' || ke.key === 'ArrowRight') {
                    ke.preventDefault();
                    const next = items[(i + 1) % items.length];
                    next.optEl.setAttribute('tabindex', '0');
                    optEl.setAttribute('tabindex', '-1');
                    next.optEl.focus();
                }
                if (ke.key === 'ArrowUp' || ke.key === 'ArrowLeft') {
                    ke.preventDefault();
                    const prev = items[(i - 1 + items.length) % items.length];
                    prev.optEl.setAttribute('tabindex', '0');
                    optEl.setAttribute('tabindex', '-1');
                    prev.optEl.focus();
                }
            });
            items.push({ optEl, glass, dot, sp, af: iaf, ev: itemEv, optValue: opt.value, kick });
        });
    }
    const handle = new LiquidRadioHandleImpl(el, currentValue, (v) => selectValue(v, false), buildItems, () => {
        destroyItems();
        el.classList.remove('lg-radio-group');
    });
    buildItems(initOpts);
    return handle;
}
// ─────────────────────────────────────────────────────────────────────────────
// Liquid File Upload
// ─────────────────────────────────────────────────────────────────────────────
class LiquidFileUploadHandleImpl extends EventEmitter {
    constructor(element, getFiles, clearFn, cleanup) {
        super();
        this.element = element;
        this._getFiles = getFiles;
        this._clearFn = clearFn;
        this._cleanup = cleanup;
    }
    get files() {
        return this._getFiles();
    }
    clear() {
        this._clearFn();
        return this;
    }
    destroy() {
        this._cleanup();
        this._emit('destroy');
    }
}
/**
 * Glass-wrapped file-upload dropzone with drag-and-drop support.
 */
function createLiquidFileUpload(target, options = {}) {
    const el = resolveEl(target);
    const { accept = '', multiple = false, placeholder = 'Drop files here or click to browse' } = options, glassOpts = __rest(options, ["accept", "multiple", "placeholder"]);
    el.classList.add('lg-file-upload');
    const content = document.createElement('div');
    content.className = 'lg-file-upload-content';
    const iconEl = document.createElement('div');
    iconEl.className = 'lg-file-upload-icon';
    iconEl.innerHTML =
        '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
            'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
            '<polyline points="16 16 12 12 8 16"/><line x1="12" y1="12" x2="12" y2="21"/>' +
            '<path d="M20.39 18.39A5 5 0 0 0 18 9h-1.26A8 8 0 1 0 3 16.3"/></svg>';
    const textEl = document.createElement('div');
    textEl.className = 'lg-file-upload-text';
    textEl.textContent = placeholder;
    const filenameEl = document.createElement('div');
    filenameEl.className = 'lg-file-upload-filename';
    filenameEl.style.display = 'none';
    content.appendChild(iconEl);
    content.appendChild(textEl);
    content.appendChild(filenameEl);
    el.appendChild(content);
    const input = document.createElement('input');
    input.type = 'file';
    input.className = 'lg-file-upload-input';
    if (accept)
        input.accept = accept;
    if (multiple)
        input.multiple = true;
    el.appendChild(input);
    const glass = createLiquidGlass(el, Object.assign({ width: 340, height: 160, radius: 16, bezelWidth: 18, glassThickness: 60, refractiveIndex: 1.4, blur: 0.5, saturation: 1.2, specularSlope: 0.6 }, glassOpts));
    const sp = new Spring(1, 400, 20);
    let af = null;
    function loop() {
        sp.setTarget(1);
        const s = sp.update(DT);
        el.style.transform = `scale(${s})`;
        glass._setScale(glass._getMaxDisp() * s);
        if (!sp.isSettled())
            af = requestAnimationFrame(loop);
        else
            af = null;
    }
    function kick() {
        if (!af)
            af = requestAnimationFrame(loop);
    }
    let currentFiles = null;
    function showFiles(files) {
        currentFiles = files;
        if (files && files.length > 0) {
            filenameEl.textContent = Array.from(files)
                .map((f) => f.name)
                .join(', ');
            filenameEl.style.display = 'block';
        }
        else {
            filenameEl.textContent = '';
            filenameEl.style.display = 'none';
        }
    }
    const handle = new LiquidFileUploadHandleImpl(el, () => currentFiles, () => {
        showFiles(null);
        input.value = '';
    }, () => {
        if (af !== null)
            cancelAnimationFrame(af);
        glass.destroy();
        ev.runAll();
        content.remove();
        input.remove();
        el.classList.remove('lg-file-upload');
        el.style.transform = '';
    });
    const ev = makeCleanupTracker();
    ev.add(input, 'change', () => {
        showFiles(input.files);
        if (input.files && input.files.length > 0)
            handle._emit('change', { files: input.files, element: el });
    });
    let dragDepth = 0;
    ev.add(el, 'dragenter', (e) => {
        e.preventDefault();
        if (++dragDepth === 1) {
            el.classList.add('lg-file-upload-drag');
            sp.setTarget(1.04);
            kick();
        }
    });
    ev.add(el, 'dragleave', () => {
        if (--dragDepth <= 0) {
            dragDepth = 0;
            el.classList.remove('lg-file-upload-drag');
            sp.setTarget(1);
            kick();
        }
    });
    ev.add(el, 'dragover', (e) => e.preventDefault());
    ev.add(el, 'drop', (e) => {
        var _a, _b;
        e.preventDefault();
        dragDepth = 0;
        el.classList.remove('lg-file-upload-drag');
        sp.setTarget(1);
        kick();
        const files = (_b = (_a = e.dataTransfer) === null || _a === void 0 ? void 0 : _a.files) !== null && _b !== void 0 ? _b : null;
        if (files && files.length > 0) {
            showFiles(files);
            handle._emit('change', { files, element: el });
        }
    });
    return handle;
}
// ─────────────────────────────────────────────────────────────────────────────
// Liquid Date Picker
// ─────────────────────────────────────────────────────────────────────────────
const DP_MONTHS = [
    'January',
    'February',
    'March',
    'April',
    'May',
    'June',
    'July',
    'August',
    'September',
    'October',
    'November',
    'December',
];
const DP_DAYS = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];
function dpParseISO(s) {
    if (!s)
        return null;
    const m = s.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    if (!m)
        return null;
    const d = new Date(parseInt(m[1]), parseInt(m[2]) - 1, parseInt(m[3]));
    return isNaN(d.getTime()) ? null : d;
}
function dpFormatISO(d) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}
function dpFormatDisplay(d) {
    return `${DP_MONTHS[d.getMonth()].slice(0, 3)} ${d.getDate()}, ${d.getFullYear()}`;
}
class LiquidDatePickerHandleImpl extends EventEmitter {
    constructor(element, date, setDate, openFn, closeFn, cleanup) {
        super();
        this.element = element;
        this._date = date;
        this._setDate = setDate;
        this._open = openFn;
        this._close = closeFn;
        this._cleanup = cleanup;
    }
    get value() {
        return this._date ? dpFormatISO(this._date) : '';
    }
    set value(s) {
        this._setDate(dpParseISO(s));
    }
    get date() {
        return this._date;
    }
    set date(d) {
        this._setDate(d);
    }
    /** @internal */ _syncDate(d) {
        this._date = d;
    }
    open() {
        this._open();
        return this;
    }
    close() {
        this._close();
        return this;
    }
    destroy() {
        this._cleanup();
        this._emit('destroy');
    }
}
/**
 * Glass-wrapped date picker with animated calendar popup.
 */
function createLiquidDatePicker(target, options = {}) {
    const el = resolveEl(target);
    const { value: initVal = '', placeholder = 'Select date', min: minStr = '', max: maxStr = '' } = options, glassOpts = __rest(options, ["value", "placeholder", "min", "max"]);
    const minDate = dpParseISO(minStr);
    const maxDate = dpParseISO(maxStr);
    let selectedDate = dpParseISO(initVal);
    el.classList.add('lg-datepicker-wrapper');
    const display = document.createElement('div');
    display.className = 'lg-datepicker-display';
    display.setAttribute('aria-haspopup', 'true');
    display.setAttribute('aria-expanded', 'false');
    const valueSpan = document.createElement('span');
    valueSpan.className = selectedDate
        ? 'lg-datepicker-value'
        : 'lg-datepicker-value lg-datepicker-placeholder';
    valueSpan.textContent = selectedDate ? dpFormatDisplay(selectedDate) : placeholder;
    const calIcon = document.createElement('span');
    calIcon.className = 'lg-datepicker-icon';
    calIcon.setAttribute('aria-hidden', 'true');
    calIcon.innerHTML =
        '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
            '<rect x="3" y="4" width="18" height="18" rx="2"/>' +
            '<line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/>' +
            '<line x1="3" y1="10" x2="21" y2="10"/></svg>';
    display.appendChild(valueSpan);
    display.appendChild(calIcon);
    el.appendChild(display);
    const popup = document.createElement('div');
    popup.className = 'lg-datepicker-popup';
    popup.style.display = 'none';
    popup.style.opacity = '0';
    popup.setAttribute('role', 'dialog');
    popup.setAttribute('aria-label', 'Date picker');
    const dpHeader = document.createElement('div');
    dpHeader.className = 'lg-datepicker-header';
    const prevBtn = document.createElement('button');
    prevBtn.type = 'button';
    prevBtn.className = 'lg-datepicker-nav';
    prevBtn.setAttribute('aria-label', 'Previous month');
    prevBtn.innerHTML =
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
            'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">' +
            '<polyline points="15 18 9 12 15 6"/></svg>';
    const monthBtn = document.createElement('button');
    monthBtn.type = 'button';
    monthBtn.className = 'lg-datepicker-month-btn';
    const nextBtn = document.createElement('button');
    nextBtn.type = 'button';
    nextBtn.className = 'lg-datepicker-nav';
    nextBtn.setAttribute('aria-label', 'Next month');
    nextBtn.innerHTML =
        '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
            'stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">' +
            '<polyline points="9 18 15 12 9 6"/></svg>';
    dpHeader.appendChild(prevBtn);
    dpHeader.appendChild(monthBtn);
    dpHeader.appendChild(nextBtn);
    popup.appendChild(dpHeader);
    const weekdaysRow = document.createElement('div');
    weekdaysRow.className = 'lg-datepicker-weekdays';
    DP_DAYS.forEach((d) => {
        const s = document.createElement('span');
        s.textContent = d;
        weekdaysRow.appendChild(s);
    });
    popup.appendChild(weekdaysRow);
    const daysGrid = document.createElement('div');
    daysGrid.className = 'lg-datepicker-days';
    popup.appendChild(daysGrid);
    el.appendChild(popup);
    const glass = createLiquidGlass(el, Object.assign({ width: 340, height: 60, radius: 16, bezelWidth: 15, glassThickness: 60, refractiveIndex: 1.5, blur: 0.5, saturation: 1.2, specularSlope: 0.7 }, glassOpts));
    const sp = new Spring(1, 400, 20);
    let af = null;
    const popupSp = new Spring(0, 500, 25);
    let popupAf = null;
    let isOpen = false;
    function loop() {
        sp.setTarget(1);
        const s = sp.update(DT);
        el.style.transform = `scale(${s})`;
        glass._setScale(glass._getMaxDisp() * s);
        if (!sp.isSettled())
            af = requestAnimationFrame(loop);
        else
            af = null;
    }
    function kick() {
        if (!af)
            af = requestAnimationFrame(loop);
    }
    function popupLoop() {
        popupSp.setTarget(isOpen ? 1 : 0);
        const v = popupSp.update(DT);
        popup.style.opacity = String(Math.max(0, v));
        popup.style.transform = `translateY(${(1 - v) * -6}px) scale(${0.97 + 0.03 * v})`;
        if (v < 0.005 && !isOpen)
            popup.style.display = 'none';
        if (!popupSp.isSettled())
            popupAf = requestAnimationFrame(popupLoop);
        else
            popupAf = null;
    }
    function kickPopup() {
        if (!popupAf)
            popupAf = requestAnimationFrame(popupLoop);
    }
    const viewDate = new Date();
    if (selectedDate)
        viewDate.setFullYear(selectedDate.getFullYear(), selectedDate.getMonth(), 1);
    else
        viewDate.setDate(1);
    let cellEv = makeCleanupTracker();
    function renderCalendar() {
        cellEv.runAll();
        cellEv = makeCleanupTracker();
        daysGrid.innerHTML = '';
        const year = viewDate.getFullYear();
        const month = viewDate.getMonth();
        monthBtn.textContent = `${DP_MONTHS[month]} ${year}`;
        const firstWeekday = new Date(year, month, 1).getDay();
        const daysInMonth = new Date(year, month + 1, 0).getDate();
        const daysInPrev = new Date(year, month, 0).getDate();
        const today = new Date();
        for (let i = 0; i < firstWeekday; i++) {
            const cell = document.createElement('button');
            cell.type = 'button';
            cell.className = 'lg-datepicker-day lg-datepicker-day-other';
            cell.textContent = String(daysInPrev - firstWeekday + i + 1);
            cell.disabled = true;
            daysGrid.appendChild(cell);
        }
        for (let d = 1; d <= daysInMonth; d++) {
            const cell = document.createElement('button');
            cell.type = 'button';
            cell.className = 'lg-datepicker-day';
            cell.textContent = String(d);
            const cellDate = new Date(year, month, d);
            if (cellDate.toDateString() === today.toDateString())
                cell.classList.add('lg-datepicker-day-today');
            if (selectedDate && cellDate.toDateString() === selectedDate.toDateString())
                cell.classList.add('lg-datepicker-day-selected');
            if ((minDate && cellDate < minDate) || (maxDate && cellDate > maxDate)) {
                cell.disabled = true;
                cell.classList.add('lg-datepicker-day-disabled');
            }
            cellEv.add(cell, 'click', () => {
                selectedDate = new Date(year, month, d);
                valueSpan.textContent = dpFormatDisplay(selectedDate);
                valueSpan.className = 'lg-datepicker-value';
                handle._syncDate(selectedDate);
                renderCalendar();
                closePopup();
                handle._emit('change', {
                    date: selectedDate,
                    value: dpFormatISO(selectedDate),
                    element: el,
                });
            });
            daysGrid.appendChild(cell);
        }
        const total = Math.ceil((firstWeekday + daysInMonth) / 7) * 7;
        for (let d = 1; d <= total - firstWeekday - daysInMonth; d++) {
            const cell = document.createElement('button');
            cell.type = 'button';
            cell.className = 'lg-datepicker-day lg-datepicker-day-other';
            cell.textContent = String(d);
            cell.disabled = true;
            daysGrid.appendChild(cell);
        }
    }
    function openPopup() {
        if (isOpen)
            return;
        isOpen = true;
        popup.style.display = 'block';
        renderCalendar();
        display.setAttribute('aria-expanded', 'true');
        sp.setTarget(1.02);
        kick();
        kickPopup();
        handle._emit('open', undefined);
    }
    function closePopup() {
        if (!isOpen)
            return;
        isOpen = false;
        display.setAttribute('aria-expanded', 'false');
        sp.setTarget(1);
        kick();
        kickPopup();
        handle._emit('close', undefined);
    }
    const onDocClick = (e) => {
        if (!el.contains(e.target))
            closePopup();
    };
    document.addEventListener('click', onDocClick);
    const handle = new LiquidDatePickerHandleImpl(el, selectedDate, (d) => {
        selectedDate = d;
        handle._syncDate(d);
        valueSpan.textContent = d ? dpFormatDisplay(d) : placeholder;
        valueSpan.className = d
            ? 'lg-datepicker-value'
            : 'lg-datepicker-value lg-datepicker-placeholder';
        if (d)
            viewDate.setFullYear(d.getFullYear(), d.getMonth(), 1);
        if (isOpen)
            renderCalendar();
    }, openPopup, closePopup, () => {
        if (af !== null)
            cancelAnimationFrame(af);
        if (popupAf !== null)
            cancelAnimationFrame(popupAf);
        document.removeEventListener('click', onDocClick);
        glass.destroy();
        cellEv.runAll();
        ev.runAll();
        display.remove();
        popup.remove();
        el.classList.remove('lg-datepicker-wrapper');
        el.style.transform = '';
    });
    const ev = makeCleanupTracker();
    ev.add(el, 'click', (e) => {
        if (popup.contains(e.target))
            return;
        if (isOpen) {
            closePopup();
        }
        else {
            openPopup();
        }
    });
    ev.add(prevBtn, 'click', (e) => {
        e.stopPropagation();
        viewDate.setMonth(viewDate.getMonth() - 1);
        renderCalendar();
    });
    ev.add(nextBtn, 'click', (e) => {
        e.stopPropagation();
        viewDate.setMonth(viewDate.getMonth() + 1);
        renderCalendar();
    });
    ev.add(monthBtn, 'click', (e) => e.stopPropagation());
    ev.add(popup, 'click', (e) => e.stopPropagation());
    return handle;
}

const DONE = '_lgInit';
function parseDataset(ds) {
    const out = {};
    const str = (k) => {
        if (ds[k] != null)
            out[k] = ds[k];
    };
    const num = (k) => {
        if (ds[k] != null)
            out[k] = parseFloat(ds[k]);
    };
    const bool = (k) => {
        if (ds[k] != null)
            out[k] = ds[k] !== 'false';
    };
    str('label');
    str('placeholder');
    str('type');
    str('profile');
    str('filterMode');
    str('accept');
    str('min');
    str('max');
    bool('checked');
    bool('multiple');
    // Parse value as a number when it looks numeric, otherwise keep as string
    // (needed so select/radio data-value="opt-id" works alongside slider data-value="50")
    if (ds['value'] != null) {
        const n = parseFloat(ds['value']);
        out['value'] = isNaN(n) ? ds['value'] : n;
    }
    num('step');
    num('rows');
    num('size');
    num('bezelWidth');
    num('glassThickness');
    num('refractiveIndex');
    num('blur');
    num('saturation');
    num('specularSlope');
    return out;
}
/**
 * Scan the document (or a sub-tree) for `data-liquid-*` attributes and apply
 * the appropriate factory to each matched element.
 *
 * @example
 * ```html
 * <button data-liquid-button  data-label="Subscribe"></button>
 * <div    data-liquid-switch  data-checked="true"></div>
 * <div    data-liquid-slider  data-min="0" data-max="100" data-value="50"></div>
 * <div    data-liquid-glass   data-bezel-width="24"></div>
 * <div    data-liquid-cursor></div>
 * <div    data-liquid-input   data-placeholder="Search…"></div>
 * <div    data-liquid-search  data-placeholder="Search…" data-debounce="300"></div>
 * <div    data-liquid-datepicker data-placeholder="Pick a date" data-min="2025-01-01"></div>
 * <div    data-liquid-radio></div>
 * <div    data-liquid-file-upload data-accept="image/*" data-multiple="true"></div>
 * <div    data-liquid-dial    data-value="0"></div>
 * <div    data-liquid-progress data-value="40"></div>
 * ```
 * ```ts
 * import { init } from '@avenra/liquid-glass';
 * const handles = init();
 * ```
 */
function init(options = {}) {
    var _a;
    const root = (_a = options.root) !== null && _a !== void 0 ? _a : document;
    const handles = [];
    function apply(selector, factory) {
        root.querySelectorAll(selector).forEach((el) => {
            if (el[DONE])
                return;
            el[DONE] = true;
            try {
                const opts = parseDataset(el.dataset);
                const handle = factory(el, opts);
                el._liquidGlassHandle = handle;
                handles.push(handle);
            }
            catch (e) {
                console.warn('[liquid-glass] init failed on element:', el, e);
            }
        });
    }
    apply('[data-liquid-button]', (el, opts) => createLiquidButton(el, opts));
    apply('[data-liquid-switch]', (el, opts) => createLiquidSwitch(el, opts));
    apply('[data-liquid-slider]', (el, opts) => createLiquidSlider(el, opts));
    apply('[data-liquid-cursor]', (el, opts) => createLiquidCursor(el, opts));
    apply('[data-liquid-input]', (el, opts) => createLiquidInput(el, opts));
    apply('[data-liquid-textarea]', (el, opts) => createLiquidTextarea(el, opts));
    apply('[data-liquid-select]', (el, opts) => createLiquidSelect(el, opts));
    apply('[data-liquid-checkbox]', (el, opts) => createLiquidCheckbox(el, opts));
    apply('[data-liquid-radio]', (el, opts) => createLiquidRadio(el, opts));
    apply('[data-liquid-file-upload]', (el, opts) => createLiquidFileUpload(el, opts));
    apply('[data-liquid-datepicker]', (el, opts) => createLiquidDatePicker(el, opts));
    apply('[data-liquid-dial]', (el, opts) => createLiquidDial(el, opts));
    apply('[data-liquid-progress]', (el, opts) => createLiquidProgress(el, opts));
    apply('[data-liquid-glass]', (el, opts) => createLiquidGlass(el, opts));
    return handles;
}

export { PROFILES, Spring, buildMaps, compute1D, compute2D, computeSpecular, createFilterSVG, createLiquidButton, createLiquidCheckbox, createLiquidCursor, createLiquidDatePicker, createLiquidDial, createLiquidFileUpload, createLiquidGlass, createLiquidInput, createLiquidProgress, createLiquidRadio, createLiquidSelect, createLiquidSlider, createLiquidSwitch, createLiquidTextarea, createLiquidTooltip, imageDataToURL, init, injectImages, maxDisp, nextFilterId, setScale, supportsBackdropFilter };
//# sourceMappingURL=liquid-glass.esm.js.map
