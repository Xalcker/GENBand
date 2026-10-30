"use strict";
// GenPlayer: toca la música de una canción de GENBand en el navegador (o en Node), con un emulador del
// YM2612 (FM) y del SN76489 (PSG) de la Genesis.
//
// La entrada es el mismo flujo por cuadro que toca la ROM (ver vgm.frame_stream y src/music.c): las
// escrituras a los registros de cada cuadro de la consola. Se emula a la frecuencia propia del YM2612 (reloj / 144,
// unos 53267 Hz) y se baja a la frecuencia de salida promediando.
//
// Cada canal (FM 1-6, PSG 1-3, ruido y DAC) se renderiza por separado: la mezcla completa es su suma, así
// que silenciar canales en el editor es sumar solo los que se oyen (como en el nesplayer.js de NESBand).
//
// No es una emulación exacta ciclo por ciclo: la estructura es la del chip (como la documenta MAME, fm.c)
// pero sin SSG-EG ni el modo especial del canal 3. Las escrituras de cada cuadro se aplican al empezar
// el cuadro, como en el juego.
//
// El DAC: el flujo dice "toca el sample n" ($54 n) y el juego se lo pasa al driver PCM del Z80, que lo
// toca a su frecuencia hasta el final o hasta el siguiente golpe. Aquí igual: opts.dac trae los samples
// (8 bits con signo y su frecuencia en Hz); mientras el DAC está encendido ($2B) sustituye al canal FM 6,
// con la misma escala que un canal FM a todo volumen (como en el chip).

const GenPlayer = (() => {
  const YM_CLOCK = 7670453;
  const PSG_CLOCK = 3579545;
  const NATIVE = YM_CLOCK / 144;           // muestras por segundo del YM2612
  // El flujo avanza un cuadro por cada cuadro de la consola: la Genesis NTSC da 59.92 por segundo
  // (reloj maestro de 53.693175 MHz / 3420 por línea / 262 líneas), no 60
  const FPS = 53693175 / 3420 / 262;
  const CHANNELS = 11;                     // FM 1-6, PSG 1-3, ruido, DAC

  // --- Tablas del YM2612 ---
  const SIN = new Float32Array(1024);
  for (let i = 0; i < 1024; i++) SIN[i] = Math.sin(((i + 0.5) * 2 * Math.PI) / 1024);
  // Atenuación de 10 bits (0.09375 dB por paso) -> amplitud; de 1024 en adelante, silencio
  const ATT = new Float32Array(1024);
  for (let i = 0; i < 1024; i++) ATT[i] = Math.pow(10, (-i * 0.09375) / 20);

  // Envolvente: cada 3 muestras, según la velocidad efectiva (0-63), cuánto sube la atenuación
  const EG_INC = [
    0, 1, 0, 1, 0, 1, 0, 1,   0, 1, 0, 1, 1, 1, 0, 1,   0, 1, 1, 1, 0, 1, 1, 1,   0, 1, 1, 1, 1, 1, 1, 1,
    1, 1, 1, 1, 1, 1, 1, 1,   1, 1, 1, 2, 1, 1, 1, 2,   1, 2, 1, 2, 1, 2, 1, 2,   1, 2, 2, 2, 1, 2, 2, 2,
    2, 2, 2, 2, 2, 2, 2, 2,   2, 2, 2, 4, 2, 2, 2, 4,   2, 4, 2, 4, 2, 4, 2, 4,   2, 4, 4, 4, 2, 4, 4, 4,
    4, 4, 4, 4, 4, 4, 4, 4,   4, 4, 4, 8, 4, 4, 4, 8,   4, 8, 4, 8, 4, 8, 4, 8,   4, 8, 8, 8, 4, 8, 8, 8,
    8, 8, 8, 8, 8, 8, 8, 8,
  ];
  const EG_SHIFT = new Uint8Array(64), EG_SELECT = new Uint8Array(64);
  for (let r = 0; r < 64; r++) {
    const rate = r >> 2;
    if (rate < 12) { EG_SHIFT[r] = 11 - rate; EG_SELECT[r] = r & 3; }
    else if (rate < 15) { EG_SHIFT[r] = 0; EG_SELECT[r] = 4 * (rate - 11) + (r & 3); }
    else { EG_SHIFT[r] = 0; EG_SELECT[r] = 16; }
  }
  // Desafinación (DT 1-3; 4-7 es lo mismo hacia abajo), por código de tecla (0-31)
  const DT = [
    [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    [0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 3, 3, 3, 4, 4, 4, 5, 5, 6, 6, 7, 8, 8, 8, 8],
    [1, 1, 1, 1, 2, 2, 2, 2, 2, 3, 3, 3, 4, 4, 4, 5, 5, 6, 6, 7, 8, 8, 9, 10, 11, 12, 13, 14, 16, 16, 16, 16],
    [2, 2, 2, 2, 2, 3, 3, 3, 4, 4, 4, 5, 5, 6, 6, 7, 8, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 20, 22, 22, 22, 22],
  ];
  const FN_NOTE = [0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 3, 3, 3, 3, 3, 3];
  const LFO_HZ = [3.98, 5.56, 6.02, 6.37, 6.88, 9.63, 48.1, 72.2];
  const PMS_CENTS = [0, 3.4, 6.7, 10, 14, 20, 40, 80];
  const AMS_SHIFT = [8, 3, 1, 0];
  // Los registros de cada canal van en el orden op1, op3, op2, op4
  const SLOT_OP = [0, 2, 1, 3];

  const OFF = 0, RELEASE = 1, SUSTAIN = 2, DECAY = 3, ATTACK = 4;

  // --- Mezcla: cuánto pesa cada canal en la salida (-1..1) ---
  // Como en la Genesis (y en MAME): el PSG entra a la mitad que el YM2612 y su salida es unipolar (0 o el
  // volumen), así que su parte alterna es la mitad de la de una onda de -1 a 1: un canal del PSG a todo
  // volumen pesa la cuarta parte que un canal FM a todo volumen
  // (el nivel total es el de MAME: el mismo VGM suena igual de fuerte en los dos, ver el README)
  const FM_GAIN = 0.085 / 8192;
  const PSG_GAIN = 0.0212;

  function newOp() {
    return { dt: 0, mul: 0, tl: 127, rs: 0, ar: 0, d1r: 0, d2r: 0, sl: 0, rr: 0, am: 0,
             phase: 0, incr: 0, vol: 1023, state: OFF, key: false };
  }
  function newChannel() {
    return { fnum: 0, block: 0, kc: 0, alg: 0, fb: 0, ams: 0, pms: 0, fb0: 0, fb1: 0,
             op: [newOp(), newOp(), newOp(), newOp()] };
  }

  function makeChip() {
    return {
      ch: [0, 1, 2, 3, 4, 5].map(newChannel), latch: [0, 0], lfoOn: false, lfoHz: 0, lfoPhase: 0, dac: false, egCnt: 0, egSub: 0,
      psg: { period: [1, 1, 1], counter: [1, 1, 1], out: [1, 1, 1], vol: [15, 15, 15, 15], noise: 0, ncount: 1, nout: 1,
             lfsr: 0x8000, latch: 0 },
    };
  }

  function updateIncr(c) {
    c.kc = (c.block << 2) | FN_NOTE[c.fnum >> 7];
    const fc = (c.fnum << c.block) >> 1;
    for (const o of c.op) {
      const dt = DT[o.dt & 3][c.kc] * (o.dt & 4 ? -1 : 1);
      const mul2 = o.mul ? o.mul * 2 : 1;
      o.incr = (((fc + dt) & 0x1ffff) * mul2) >> 1;
    }
  }

  function keyOn(o) {
    if (o.key) return;
    o.key = true;
    o.phase = 0;
    o.state = ATTACK;
  }
  function keyOff(o) {
    if (!o.key) return;
    o.key = false;
    if (o.state > RELEASE) o.state = RELEASE;
  }

  function writeYM(chip, port, reg, v) {
    if (port === 0 && reg < 0x30) {
      if (reg === 0x22) { chip.lfoOn = !!(v & 8); chip.lfoHz = LFO_HZ[v & 7]; }
      else if (reg === 0x28) {
        const code = v & 7;
        if (code === 3 || code === 7) return;
        const c = chip.ch[code < 3 ? code : code - 1];
        // bits 4-7: op1, op2, op3, op4
        for (let i = 0; i < 4; i++) ((v >> (4 + i)) & 1 ? keyOn : keyOff)(c.op[i]);
      } else if (reg === 0x2b) chip.dac = !!(v & 0x80);
      return;
    }
    const n = reg & 3;
    if (n === 3) return;
    const c = chip.ch[port * 3 + n];
    if (reg >= 0x30 && reg < 0xa0) {
      const o = c.op[SLOT_OP[(reg >> 2) & 3]];
      switch (reg & 0xf0) {
        case 0x30: o.dt = (v >> 4) & 7; o.mul = v & 15; updateIncr(c); break;
        case 0x40: o.tl = v & 127; break;
        case 0x50: o.rs = v >> 6; o.ar = v & 31; break;
        case 0x60: o.am = v >> 7; o.d1r = v & 31; break;
        case 0x70: o.d2r = v & 31; break;
        case 0x80: o.sl = (v >> 4) === 15 ? 992 : (v >> 4) * 32; o.rr = v & 15; break;
        default: break;   // $90: SSG-EG (no se emula)
      }
    } else if (reg >= 0xa4 && reg <= 0xa6) chip.latch[port] = v;
    else if (reg >= 0xa0 && reg <= 0xa2) {
      c.fnum = ((chip.latch[port] & 7) << 8) | v;
      c.block = (chip.latch[port] >> 3) & 7;
      updateIncr(c);
    } else if (reg >= 0xb0 && reg <= 0xb2) { c.fb = (v >> 3) & 7; c.alg = v & 7; c.fb0 = c.fb1 = 0; }
    else if (reg >= 0xb4 && reg <= 0xb6) { c.ams = (v >> 4) & 3; c.pms = v & 7; }
  }

  function writePSG(chip, v) {
    const p = chip.psg;
    if (v & 0x80) p.latch = v;
    const ch = (p.latch >> 5) & 3, isVol = p.latch & 0x10;
    if (isVol) { p.vol[ch] = v & 15; return; }
    if (ch === 3) {
      p.noise = v & 7;
      p.lfsr = 0x8000;
      return;
    }
    p.period[ch] = v & 0x80 ? (p.period[ch] & 0x3f0) | (v & 15) : (p.period[ch] & 15) | ((v & 0x3f) << 4);
  }

  // La velocidad efectiva (0-63) de una etapa de la envolvente
  function rate(r, o, c) {
    if (!r) return 0;
    return Math.min(63, r + (c.kc >> (3 - o.rs)));
  }

  function stepEnvelope(chip) {
    const cnt = ++chip.egCnt;
    for (const c of chip.ch) {
      for (const o of c.op) {
        if (o.state === OFF) continue;
        let r;
        if (o.state === ATTACK) r = rate(o.ar * 2, o, c);
        else if (o.state === DECAY) r = rate(o.d1r * 2, o, c);
        else if (o.state === SUSTAIN) r = rate(o.d2r * 2, o, c);
        else r = rate(o.rr * 4 + 2, o, c);
        if (o.state === ATTACK && r >= 62) { o.vol = 0; o.state = DECAY; continue; }
        if (!r) continue;
        const shift = EG_SHIFT[r];
        if (cnt & ((1 << shift) - 1)) continue;
        const inc = EG_INC[EG_SELECT[r] * 8 + ((cnt >> shift) & 7)];
        if (o.state === ATTACK) {
          o.vol += (~o.vol * inc) >> 4;
          if (o.vol <= 0) { o.vol = 0; o.state = DECAY; }
        } else {
          o.vol += inc;
          if (o.state === DECAY && o.vol >= o.sl) o.state = SUSTAIN;
          if (o.vol >= 1023) { o.vol = 1023; if (o.state === RELEASE) o.state = OFF; }
        }
      }
    }
  }

  // La salida de un operador (en la escala del chip, unos +-8192) con la modulación `mod` (en índices de seno)
  function op(o, mod, amAtt) {
    const att = o.vol + (o.tl << 3) + (o.am ? amAtt : 0);
    if (att >= 1024) return 0;
    return SIN[((o.phase >> 10) + (mod | 0)) & 1023] * ATT[att] * 8192;
  }

  function channelSample(chip, c, lfoTri) {
    const amAtt = chip.lfoOn ? (Math.round(lfoTri * 126) >> AMS_SHIFT[c.ams]) : 0;
    let pm = 1;
    if (chip.lfoOn && c.pms) pm = Math.pow(2, ((lfoTri * 2 - 1) * PMS_CENTS[c.pms]) / 1200);
    for (const o of c.op) o.phase = (o.phase + o.incr * pm) % 1048576;
    const [o1, o2, o3, o4] = c.op;
    const fb = c.fb ? (c.fb0 + c.fb1) * Math.pow(2, c.fb - 10) : 0;
    const m1 = op(o1, fb, amAtt);
    c.fb1 = c.fb0;
    c.fb0 = m1;
    let out;
    switch (c.alg) {
      case 0: out = op(o4, op(o3, op(o2, m1 / 2, amAtt) / 2, amAtt) / 2, amAtt); break;
      case 1: out = op(o4, op(o3, (m1 + op(o2, 0, amAtt)) / 2, amAtt) / 2, amAtt); break;
      case 2: out = op(o4, (m1 + op(o3, op(o2, 0, amAtt) / 2, amAtt)) / 2, amAtt); break;
      case 3: out = op(o4, (op(o2, m1 / 2, amAtt) + op(o3, 0, amAtt)) / 2, amAtt); break;
      case 4: out = op(o2, m1 / 2, amAtt) + op(o4, op(o3, 0, amAtt) / 2, amAtt); break;
      case 5: out = op(o2, m1 / 2, amAtt) + op(o3, m1 / 2, amAtt) + op(o4, m1 / 2, amAtt); break;
      case 6: out = op(o2, m1 / 2, amAtt) + op(o3, 0, amAtt) + op(o4, 0, amAtt); break;
      default: out = m1 + op(o2, 0, amAtt) + op(o3, 0, amAtt) + op(o4, 0, amAtt); break;
    }
    return Math.max(-8192, Math.min(8191, out));
  }

  const PSG_TICKS = PSG_CLOCK / 16 / NATIVE;   // tics del PSG por muestra del YM2612
  const PSG_VOL = Array.from({ length: 16 }, (_, i) => (i === 15 ? 0 : Math.pow(10, (-2 * i) / 20)));

  // Los 3 tonos y el ruido del PSG, una muestra: escribe en out[6..9]
  function psgSample(chip, out) {
    const p = chip.psg;
    for (let i = 0; i < 3; i++) {
      p.counter[i] -= PSG_TICKS;
      const period = p.period[i] || 1;
      while (p.counter[i] <= 0) { p.counter[i] += period; p.out[i] = -p.out[i]; }
      out[6 + i] = p.period[i] > 1 ? p.out[i] * PSG_VOL[p.vol[i]] : 0;   // (un periodo de 0 o 1 es una señal fija)
    }
    p.ncount -= PSG_TICKS;
    const rateN = p.noise & 3;
    const nperiod = rateN === 3 ? (p.period[2] || 1) : 16 << rateN;
    while (p.ncount <= 0) {
      p.ncount += nperiod;
      p.nout = -p.nout;
      if (p.nout > 0) {
        const fb = p.noise & 4 ? ((p.lfsr & 1) ^ ((p.lfsr >> 3) & 1)) : p.lfsr & 1;
        p.lfsr = (p.lfsr >> 1) | (fb << 15);
      }
    }
    out[9] = (p.lfsr & 1 ? 1 : -1) * PSG_VOL[p.vol[3]];
  }

  // Aplica las escrituras de un cuadro del flujo. Devuelve la nueva posición, o -1 al terminar.
  function frameWrites(chip, s, pos, state) {
    if (state.wait) { state.wait--; return pos; }
    while (pos < s.length) {
      const cmd = s[pos++];
      if (cmd === 0x52 || cmd === 0x53) { writeYM(chip, cmd - 0x52, s[pos], s[pos + 1]); pos += 2; }
      else if (cmd === 0x50) writePSG(chip, s[pos++]);
      else if (cmd === 0x54) state.dacStart = s[pos++];
      else if (cmd === 0x62) return pos;
      else if ((cmd & 0xf0) === 0x70) { state.wait = cmd & 15; return pos; }
      else if (cmd === 0x61) { state.wait = s[pos] | (s[pos + 1] << 8); return pos + 2; }
      else return -1;   // $66: fin
    }
    return -1;
  }

  // Toca `frames` cuadros del flujo. opts: sampleRate (44100), dac ([{data: bytes con signo, rate: Hz}], los
  // samples de la canción), onProgress(f), yieldFn() (para no colgar la página). Devuelve { audio: Float32Array (la mezcla), stems: [Int16Array o null por canal], sampleRate }.
  async function render(stream, frames, opts = {}) {
    const rate = opts.sampleRate || 44100;
    const total = Math.ceil((frames / FPS) * rate);
    const audio = new Float32Array(total);
    const stems = new Array(CHANNELS).fill(null);
    const chip = makeChip();
    const st = { wait: 0, dacStart: -1 };
    const samples = opts.dac || [];
    let dacData = null, dacPos = 0, dacStep = 0;
    const ch = new Float32Array(CHANNELS);
    const acc = new Float64Array(CHANNELS);
    const gains = [0, 1, 2, 3, 4, 5].map(() => FM_GAIN).concat([PSG_GAIN, PSG_GAIN, PSG_GAIN, PSG_GAIN, FM_GAIN]);
    let pos = 0, native = 0, outIndex = 0, accCount = 0;
    const perOut = NATIVE / rate;
    let nextOut = perOut;
    for (let f = 0; f < frames && outIndex < total; f++) {
      if (pos >= 0) pos = frameWrites(chip, stream, pos, st);
      if (st.dacStart >= 0) {
        const smp = samples[st.dacStart];
        if (smp) { dacData = smp.data; dacPos = 0; dacStep = smp.rate / NATIVE; }
        st.dacStart = -1;
      }
      const end = ((f + 1) * NATIVE) / FPS;
      for (; native < end; native++) {
        if (++chip.egSub === 3) { chip.egSub = 0; stepEnvelope(chip); }
        const lfoTri = chip.lfoOn ? 1 - Math.abs(((chip.lfoPhase = (chip.lfoPhase + chip.lfoHz / NATIVE) % 1) * 2) - 1) : 0;
        for (let i = 0; i < 6; i++) ch[i] = i === 5 && chip.dac ? 0 : channelSample(chip, chip.ch[i], lfoTri);
        psgSample(chip, ch);
        ch[10] = 0;
        if (dacData) {
          const b = dacData[dacPos | 0];
          if (chip.dac) ch[10] = (b > 127 ? b - 256 : b) * 64;
          if ((dacPos += dacStep) >= dacData.length) dacData = null;
        }
        for (let i = 0; i < CHANNELS; i++) acc[i] += ch[i];
        accCount++;
        if (native + 1 >= nextOut) {
          let mix = 0;
          for (let i = 0; i < CHANNELS; i++) {
            const v = (acc[i] / accCount) * gains[i];
            acc[i] = 0;
            if (v !== 0 && !stems[i]) stems[i] = new Int16Array(total);
            if (stems[i]) stems[i][outIndex] = Math.max(-32767, Math.min(32767, Math.round(v * 32767)));
            mix += v;
          }
          accCount = 0;
          audio[outIndex++] = Math.max(-1, Math.min(1, mix));
          nextOut += perOut;
          if (outIndex >= total) break;
        }
      }
      if (f % 300 === 299) {
        if (opts.onProgress) opts.onProgress(f / frames);
        if (opts.yieldFn) await opts.yieldFn();
      }
    }
    return { audio, stems, sampleRate: rate };
  }

  return { render, FPS, CHANNELS, NATIVE };
})();

if (typeof module !== "undefined") module.exports = GenPlayer;
