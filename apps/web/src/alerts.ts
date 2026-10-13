let context: AudioContext | undefined;
document.addEventListener(
  'pointerdown',
  () => {
    try {
      context ??= new AudioContext();
      if (context.state === 'suspended') void context.resume().catch(() => {});
    } catch {}
  },
  { capture: true },
);
export function approvalSound() {
  if ((window as any).desktop) return;
  try {
    if (!context || context.state !== 'running') return;
    const oscillator = context.createOscillator(),
      gain = context.createGain();
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.frequency.value = 740;
    gain.gain.setValueAtTime(0.07, context.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.3);
    oscillator.start();
    oscillator.stop(context.currentTime + 0.3);
  } catch {}
}
