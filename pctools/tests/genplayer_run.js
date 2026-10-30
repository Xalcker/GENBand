"use strict";
// Corre genplayer.js en Node: node genplayer_run.js flujo.bin cuadros [salida.wav] [dac.json]
// (dac.json: los samples del DAC, [{"data": base64 de los bytes con signo, "rate": Hz}])
// Escribe la mezcla como WAV (16 bits, 44100 Hz, mono) e imprime en JSON el RMS de la mezcla y de cada canal.
const fs = require("fs");
const path = require("path");
const GenPlayer = require(path.join(__dirname, "..", "genband_tools", "genplayer.js"));

async function main() {
  const [streamPath, framesText, wavPath, dacPath] = process.argv.slice(2);
  const stream = new Uint8Array(fs.readFileSync(streamPath));
  const dac = dacPath ? JSON.parse(fs.readFileSync(dacPath, "utf8")).map((d) => ({ data: new Uint8Array(Buffer.from(d.data, "base64")), rate: d.rate })) : [];
  const started = Date.now();
  const result = await GenPlayer.render(stream, Number(framesText), { sampleRate: 44100, dac });
  const seconds = (Date.now() - started) / 1000;
  const rms = (arr, scale) => {
    if (!arr) return 0;
    let sum = 0;
    for (let i = 0; i < arr.length; i++) sum += (arr[i] / scale) ** 2;
    return Math.sqrt(sum / arr.length);
  };
  // La mezcla debe ser la suma de los canales (eso usa el editor para silenciar)
  let maxDiff = 0;
  for (let i = 0; i < result.audio.length; i += 97) {
    let sum = 0;
    for (const s of result.stems) if (s) sum += s[i] / 32767;
    maxDiff = Math.max(maxDiff, Math.abs(Math.max(-1, Math.min(1, sum)) - result.audio[i]));
  }
  if (wavPath) {
    const n = result.audio.length;
    const buf = Buffer.alloc(44 + n * 2);
    buf.write("RIFF", 0); buf.writeUInt32LE(36 + n * 2, 4); buf.write("WAVE", 8); buf.write("fmt ", 12);
    buf.writeUInt32LE(16, 16); buf.writeUInt16LE(1, 20); buf.writeUInt16LE(1, 22); buf.writeUInt32LE(44100, 24);
    buf.writeUInt32LE(88200, 28); buf.writeUInt16LE(2, 32); buf.writeUInt16LE(16, 34); buf.write("data", 36);
    buf.writeUInt32LE(n * 2, 40);
    for (let i = 0; i < n; i++) buf.writeInt16LE(Math.round(result.audio[i] * 32767), 44 + i * 2);
    fs.writeFileSync(wavPath, buf);
  }
  console.log(JSON.stringify({
    seconds, samples: result.audio.length, rms: rms(result.audio, 1),
    channels: result.stems.map((s) => rms(s, 32767)), mixError: maxDiff,
  }));
}
main();
