/** @type {import('next').NextConfig} */
// Standalone is required for Docker and for @netlify/plugin-nextjs v5 (expects `.next/standalone`).
const nextConfig = {
    output: 'standalone',
    reactStrictMode: true,
    // Ensure React 19 compatibility
    experimental: {
      ppr: false,
    },
    // Force CSS processing
    compiler: {
      // Enable SWC CSS processing
      styledComponents: true,
    },
    webpack: (config, { dev, isServer }) => {
      // Ensure CSS is processed correctly
      if (!dev && !isServer) {
        config.resolve.fallback = {
          ...config.resolve.fallback,
          fs: false,
        }
      }
      return config
    }
  }
  
  export default nextConfig
  