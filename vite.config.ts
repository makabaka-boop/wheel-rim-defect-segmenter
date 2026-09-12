import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  // Compose 网络内通过服务名访问（如 http://web:5173）时 Host 头不是
  // localhost，Vite 的 Host 检查会返回 403，需要显式放行；可用
  // VITE_ALLOWED_HOSTS（逗号分隔）追加其他主机名。
  const allowedHosts = [
    'web',
    ...(env.VITE_ALLOWED_HOSTS
      ? env.VITE_ALLOWED_HOSTS.split(',').map((host) => host.trim()).filter(Boolean)
      : []),
  ];
  return {
    plugins: [react()],
    server: {
      host: '0.0.0.0',
      port: 5173,
      allowedHosts,
      proxy: {
        '/api': {
          target: env.VITE_API_PROXY_TARGET || 'http://localhost:8000',
          changeOrigin: true,
        },
      },
    },
    preview: {
      host: '0.0.0.0',
      port: 4173,
      allowedHosts,
    },
  };
});
