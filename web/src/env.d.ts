/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 后端根地址（不含 /api），留空则同源相对路径。例：https://api.example.com */
  readonly VITE_API_BASE?: string
}
