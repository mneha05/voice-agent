// Playback-side AudioWorklet. Holds a queue of Float32 chunks (24 kHz, decoded
// on the main thread) and plays them out sample-accurately. A "clear" message
// empties the queue instantly — that is what makes barge-in feel immediate.
class PlayerProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._queue = [];
    this._cur = null;
    this._pos = 0;
    this.port.onmessage = (e) => {
      const d = e.data;
      if (d.cmd === "clear") {
        this._queue = [];
        this._cur = null;
        this._pos = 0;
      } else if (d.samples) {
        this._queue.push(d.samples);
      }
    };
  }
  process(_inputs, outputs) {
    const out = outputs[0][0];
    let playing = false;
    for (let i = 0; i < out.length; i++) {
      if (!this._cur || this._pos >= this._cur.length) {
        this._cur = this._queue.shift() || null;
        this._pos = 0;
      }
      if (this._cur) {
        out[i] = this._cur[this._pos++];
        playing = true;
      } else {
        out[i] = 0;
      }
    }
    // Report whether audio is actively flowing (drives the "speaking" viz).
    this.port.postMessage({ playing, depth: this._queue.length });
    return true;
  }
}
registerProcessor("player-processor", PlayerProcessor);
