/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: process.env.INTERNAL_API_URL || 'http://127.0.0.1:8000/api/:path*',
      },
      {
        source: '/stream/:path*',
        // WHEP/WebRTC signaling terminates at mediamtx (:8889), not the API
        destination: process.env.INTERNAL_MEDIAMTX_WHEP_URL || 'http://host.docker.internal:8889/stream/:path*',
      },
      {
        source: '/hls/:path*',
        // HLS segments served by mediamtx (:8888); /hls prefix stripped
        destination: process.env.INTERNAL_MEDIAMTX_HLS_URL || 'http://host.docker.internal:8888/:path*',
      },
    ];
  },
};

module.exports = nextConfig;
