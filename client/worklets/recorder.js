// Capture-side AudioWorklet. Runs in the audio thread, collects mono Float32
// mic samples (the capture context is created at 16 kHz, so no resampling here),
// batches them to ~32 ms and ships them to the main thread for encoding.
class RecorderProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buf = [];
    this._target = 512; // samples (~32 ms @ 16 kHz)
  }
  process(inputs) {
    const ch = inputs[0][0];
    if (!ch) return true;
    // Copy: the underlying buffer is reused by the engine after process().
    for (let i = 0; i < ch.length; i++) this._buf.push(ch[i]);
    let rms = 0;
    for (let i = 0; i < ch.length; i++) rms += ch[i] * ch[i];
    rms = Math.sqrt(rms / ch.length);
    if (this._buf.length >= this._target) {
      this.port.postMessage({ samples: Float32Array.from(this._buf), rms });
      this._buf = [];
    }
    return true;
  }
}
registerProcessor("recorder-processor", RecorderProcessor);
