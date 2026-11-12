/** @type {import('next').NextConfig} */
const config = {
  output: 'standalone',
  images: {unoptimized: true},
  distDir: process.env.RECARENA_NEXT_BUILD_DIR || '.next',
  poweredByHeader: false,
  reactStrictMode: true,
  skipTrailingSlashRedirect: true,
  async headers() {
    return [{source:'/:path*',headers:[
      {key:'X-Robots-Tag',value:'noindex'},
      {key:'Referrer-Policy',value:'no-referrer'},
      {key:'X-Content-Type-Options',value:'nosniff'},
    ]}];
  },
  async rewrites() {
    return {beforeFiles:[
      {source:'/health',destination:'/api/health'},
      {source:'/s/:sessionId/api/shop/:path*',destination:'/api/_shop/:sessionId/:path*'},
      {source:'/s/:sessionId/assets/:path*',destination:'/api/_assets/:sessionId/:path*'},
    ],afterFiles:[],fallback:[]};
  },
};
export default config;
