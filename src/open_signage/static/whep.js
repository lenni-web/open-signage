// WebRTC-Wiedergabe der Live-Übertragung über die WHEP-Weiterleitung von Open Signage.
// Wird vom Player und von der Vorschau in der Verwaltung gemeinsam genutzt.

function waitForIceGathering(peer, timeoutMs = 2000) {
  if (peer.iceGatheringState === "complete") return Promise.resolve();
  return new Promise(resolve => {
    const timeout = window.setTimeout(resolve, timeoutMs);
    peer.addEventListener("icegatheringstatechange", () => {
      if (peer.iceGatheringState === "complete") {
        window.clearTimeout(timeout);
        resolve();
      }
    });
  });
}

function connectLive(video, { onStatus, onFailure, authHeaders = () => ({}) }) {
  let closed = false;
  let peer = null;
  let sessionUrl = null;
  let retryTimer;
  let disconnectTimer;
  const cleanup = () => {
    window.clearTimeout(disconnectTimer);
    if (peer) {
      peer.close();
      peer = null;
    }
    if (sessionUrl) {
      fetch(sessionUrl, { method: "DELETE", headers: authHeaders() }).catch(() => {});
      sessionUrl = null;
    }
  };
  const retry = (text) => {
    cleanup();
    if (closed) return;
    if (onFailure?.()) return;
    onStatus(text);
    window.clearTimeout(retryTimer);
    retryTimer = window.setTimeout(connect, 3000);
  };
  async function connect() {
    if (closed) return;
    try {
      peer = new RTCPeerConnection();
      const current = peer;
      peer.addTransceiver("video", { direction: "recvonly" });
      peer.addTransceiver("audio", { direction: "recvonly" });
      const stream = new MediaStream();
      video.srcObject = stream;
      peer.addEventListener("track", event => stream.addTrack(event.track));
      peer.addEventListener("connectionstatechange", () => {
        if (current !== peer) return;
        if (["failed", "closed"].includes(peer.connectionState)) {
          retry("Verbindung unterbrochen – neuer Versuch …");
        } else if (peer.connectionState === "disconnected") {
          window.clearTimeout(disconnectTimer);
          disconnectTimer = window.setTimeout(() => {
            if (current === peer && peer.connectionState !== "connected") retry("Verbindung unterbrochen – neuer Versuch …");
          }, 4000);
        }
      });
      await peer.setLocalDescription(await peer.createOffer());
      await waitForIceGathering(peer);
      const response = await fetch("/api/player/live/whep", {
        method: "POST",
        headers: { "Content-Type": "application/sdp", ...authHeaders() },
        body: peer.localDescription.sdp,
      });
      if (!response.ok) throw new Error("offline");
      sessionUrl = response.headers.get("Location");
      if (current !== peer) return;
      await peer.setRemoteDescription({ type: "answer", sdp: await response.text() });
    } catch (_) {
      retry("Warte auf Signal aus OBS …");
    }
  }
  connect();
  return {
    close() {
      closed = true;
      window.clearTimeout(retryTimer);
      cleanup();
    },
  };
}
