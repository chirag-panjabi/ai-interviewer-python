/**
 * audio.js - Web Audio DSP for Gemini Live API
 * 
 * Capabilities:
 * - 24kHz Int16 PCM audio playback with 150ms jitter buffer
 * - Instant barge-in interruption (buffer draining)
 * - 16kHz mono microphone recording with real-time linear downsampling
 * - Real-time RMS volume analysis for VoiceOrbs
 */

export class LiveAudioPlayer {
  constructor() {
    this.ctx = null;
    this.masterGainNode = null;
    this.analyser = null;
    this.analyserData = null;
    this.nextPlayTime = 0;
    this.activeSources = [];
    this.remainderByte = null;
    this.isMuted = false;
  }

  warmUp() {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;

      if (!this.ctx || this.ctx.state === "closed") {
        try {
          this.ctx = new AudioCtx({ sampleRate: 24000 });
        } catch {
          this.ctx = new AudioCtx();
        }

        this.masterGainNode = this.ctx.createGain();
        this.masterGainNode.gain.value = this.isMuted ? 0 : 1.0;
        this.masterGainNode.connect(this.ctx.destination);

        this.analyser = this.ctx.createAnalyser();
        this.analyser.fftSize = 256;
        this.analyser.smoothingTimeConstant = 0.8;
        this.analyserData = new Uint8Array(this.analyser.fftSize);
        this.masterGainNode.connect(this.analyser);
      }

      if (this.ctx.state === "suspended") {
        this.ctx.resume().catch(() => {});
      }

      // Unlock browser audio hardware with 1ms silent buffer
      const silentBuffer = this.ctx.createBuffer(1, 24, 24000);
      const source = this.ctx.createBufferSource();
      source.buffer = silentBuffer;
      source.connect(this.masterGainNode || this.ctx.destination);
      source.start(0);

      this.nextPlayTime = 0;
    } catch (e) {
      console.warn("[LiveAudioPlayer] Warm-up warning:", e);
    }
  }

  enqueueChunk(base64Pcm, sampleRate = 24000) {
    if (!this.ctx || this.ctx.state === "closed") {
      this.warmUp();
    }
    const ctx = this.ctx;
    if (!ctx) return;

    if (ctx.state === "suspended") {
      ctx.resume().catch(() => {});
    }

    try {
      const binary = atob(base64Pcm);
      const incomingLen = binary.length;
      if (incomingLen === 0) return;

      const hasRemainder = this.remainderByte !== null;
      const totalBytesLen = incomingLen + (hasRemainder ? 1 : 0);

      const bytes = new Uint8Array(totalBytesLen);
      let offset = 0;
      if (hasRemainder) {
        bytes[0] = this.remainderByte;
        offset = 1;
        this.remainderByte = null;
      }

      for (let i = 0; i < incomingLen; i++) {
        bytes[offset + i] = binary.charCodeAt(i);
      }

      // Keep odd trailing byte for 16-bit word alignment
      if (totalBytesLen % 2 !== 0) {
        this.remainderByte = bytes[totalBytesLen - 1];
      }

      const numSamples = Math.floor(totalBytesLen / 2);
      if (numSamples === 0) return;

      const int16 = new Int16Array(bytes.buffer, 0, numSamples);
      const float32 = new Float32Array(numSamples);

      for (let i = 0; i < numSamples; i++) {
        float32[i] = int16[i] / 32768.0;
      }

      const audioBuffer = ctx.createBuffer(1, numSamples, sampleRate);
      audioBuffer.copyToChannel(float32, 0);

      const source = ctx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(this.masterGainNode || ctx.destination);

      const now = ctx.currentTime;
      // 150ms jitter buffer absorbs network packet timing jitter
      if (this.nextPlayTime === 0 || this.nextPlayTime < now) {
        if (this.nextPlayTime === 0 || now - this.nextPlayTime > 0.08) {
          this.nextPlayTime = now + 0.15;
        } else {
          this.nextPlayTime = now;
        }
      }

      const startTime = this.nextPlayTime;
      source.start(startTime);
      this.nextPlayTime = startTime + audioBuffer.duration;

      this.activeSources.push(source);
      source.onended = () => {
        const idx = this.activeSources.indexOf(source);
        if (idx !== -1) {
          this.activeSources.splice(idx, 1);
        }
      };
    } catch (err) {
      console.error("[LiveAudioPlayer] Error enqueuing audio:", err);
    }
  }

  interrupt() {
    for (const source of this.activeSources) {
      try {
        source.stop();
        source.disconnect();
      } catch {}
    }
    this.activeSources = [];
    this.remainderByte = null;
    if (this.ctx) {
      this.nextPlayTime = 0;
    }
  }

  setMute(isMuted) {
    this.isMuted = isMuted;
    if (this.masterGainNode) {
      this.masterGainNode.gain.value = isMuted ? 0 : 1.0;
    }
  }

  getVolumeLevel() {
    if (!this.analyser || !this.analyserData || this.activeSources.length === 0) {
      return 0;
    }
    this.analyser.getByteTimeDomainData(this.analyserData);
    let sum = 0;
    for (let i = 0; i < this.analyserData.length; i++) {
      const v = (this.analyserData[i] - 128) / 128;
      sum += v * v;
    }
    const rms = Math.sqrt(sum / this.analyserData.length);
    return Math.min(1.0, rms * 4.0);
  }

  close() {
    this.interrupt();
    if (this.masterGainNode) {
      try { this.masterGainNode.disconnect(); } catch {}
      this.masterGainNode = null;
    }
    if (this.analyser) {
      try { this.analyser.disconnect(); } catch {}
      this.analyser = null;
    }
    if (this.ctx && this.ctx.state !== "closed") {
      this.ctx.close().catch(() => {});
      this.ctx = null;
    }
    this.nextPlayTime = 0;
  }
}

export class LiveMicrophoneRecorder {
  constructor(onPcmData) {
    this.onPcmData = onPcmData;
    this.mediaStream = null;
    this.audioCtx = null;
    this.sourceNode = null;
    this.processorNode = null;
    this.silentGainNode = null;
    this.currentVolume = 0;
    this.isMuted = false;
  }

  async start() {
    this.mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });

    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) throw new Error("AudioContext not supported in this browser");
    this.audioCtx = new AudioCtx();

    if (this.audioCtx.state === "suspended") {
      await this.audioCtx.resume();
    }

    this.sourceNode = this.audioCtx.createMediaStreamSource(this.mediaStream);

    // 2048 buffer gives ~42ms low latency at 48kHz
    this.processorNode = this.audioCtx.createScriptProcessor(2048, 1, 1);

    this.processorNode.onaudioprocess = (e) => {
      if (this.isMuted) {
        this.currentVolume = 0;
        return;
      }

      if (this.audioCtx && this.audioCtx.state === "suspended") {
        this.audioCtx.resume().catch(() => {});
      }

      const inputData = e.inputBuffer.getChannelData(0);
      this.currentVolume = this.calcRms(inputData);

      // Downsample input data to 16kHz
      const resampled16k = this.resampleTo16k(inputData, this.audioCtx.sampleRate || 48000);
      const base64 = this.float32ToBase64PCM(resampled16k);

      if (this.onPcmData) {
        this.onPcmData(base64);
      }
    };

    this.sourceNode.connect(this.processorNode);

    // Mute local feedback to speakers
    this.silentGainNode = this.audioCtx.createGain();
    this.silentGainNode.gain.value = 0;
    this.processorNode.connect(this.silentGainNode);
    this.silentGainNode.connect(this.audioCtx.destination);
  }

  setMute(isMuted) {
    this.isMuted = isMuted;
    if (this.mediaStream) {
      this.mediaStream.getAudioTracks().forEach(track => {
        track.enabled = !isMuted;
      });
    }
  }

  getVolumeLevel() {
    return this.isMuted ? 0 : this.currentVolume;
  }

  calcRms(samples) {
    let sum = 0;
    for (let i = 0; i < samples.length; i++) {
      const v = samples[i];
      sum += v * v;
    }
    const rms = Math.sqrt(sum / (samples.length || 1));
    return Math.min(1.0, rms * 4.5);
  }

  resampleTo16k(audioData, inputSampleRate) {
    if (inputSampleRate === 16000) return audioData;
    const ratio = inputSampleRate / 16000;
    const newLength = Math.round(audioData.length / ratio);
    const result = new Float32Array(newLength);
    for (let i = 0; i < newLength; i++) {
      const originalIndex = i * ratio;
      const indexFloor = Math.floor(originalIndex);
      const indexCeil = Math.min(audioData.length - 1, indexFloor + 1);
      const fraction = originalIndex - indexFloor;
      result[i] = audioData[indexFloor] * (1 - fraction) + audioData[indexCeil] * fraction;
    }
    return result;
  }

  float32ToBase64PCM(input) {
    const len = input.length;
    const bytes = new Uint8Array(len * 2);

    for (let i = 0; i < len; i++) {
      const s = Math.max(-1, Math.min(1, input[i]));
      const int16 = s < 0 ? s * 0x8000 : s * 0x7fff;
      bytes[i * 2] = int16 & 0xff;
      bytes[i * 2 + 1] = (int16 >> 8) & 0xff;
    }

    let binary = "";
    const chunkSize = 0x8000;
    for (let i = 0; i < bytes.length; i += chunkSize) {
      const chunk = bytes.subarray(i, Math.min(i + chunkSize, bytes.length));
      binary += String.fromCharCode.apply(null, chunk);
    }
    return btoa(binary);
  }

  stop() {
    if (this.sourceNode) {
      this.sourceNode.disconnect();
      this.sourceNode = null;
    }
    if (this.processorNode) {
      this.processorNode.disconnect();
      this.processorNode = null;
    }
    if (this.silentGainNode) {
      this.silentGainNode.disconnect();
      this.silentGainNode = null;
    }
    if (this.audioCtx && this.audioCtx.state !== "closed") {
      this.audioCtx.close().catch(() => {});
      this.audioCtx = null;
    }
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach(track => track.stop());
      this.mediaStream = null;
    }
    this.currentVolume = 0;
  }
}
