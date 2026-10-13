export {};
declare global {
  interface Window {
    desktop?: { pickDirectory(): Promise<string | null> };
  }
}
