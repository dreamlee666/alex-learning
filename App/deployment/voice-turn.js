/* Local pause detection; no microphone data is sent until a turn is submitted. */
(function(root) {
  class VoiceTurnDetector {
    constructor({silenceMs=2000,minSpeechMs=160,maxTurnMs=110000}={}) {
      this.silenceMs=silenceMs;this.minSpeechMs=minSpeechMs;this.maxTurnMs=maxTurnMs;this.reset();
    }
    reset(){this.noise=.002;this.active=false;this.started=0;this.lastVoice=0;this.speechMs=0;this.candidateMs=0}
    feed(rms,durationMs,now) {
      const threshold=Math.max(.009,Math.min(.025,this.noise*3));
      const voiced=rms>threshold;
      if(!voiced&&!this.active)this.noise=.98*this.noise+.02*Math.min(rms,.008);
      if(voiced){
        this.candidateMs+=durationMs;
        if(!this.active&&this.candidateMs>=this.minSpeechMs){this.active=true;this.started=now-this.candidateMs;this.speechMs=this.candidateMs}
        else if(this.active)this.speechMs+=durationMs;
        this.lastVoice=now;
      }else if(!this.active)this.candidateMs=Math.max(0,this.candidateMs-durationMs*2);
      if(this.active&&(now-this.lastVoice>=this.silenceMs||now-this.started>=this.maxTurnMs)){
        this.active=false;this.candidateMs=0;return 'end';
      }
      return this.active?'speech':'idle';
    }
  }
  root.VoiceTurnDetector=VoiceTurnDetector;
  if(typeof module!=='undefined')module.exports=VoiceTurnDetector;
})(typeof window!=='undefined'?window:globalThis);
