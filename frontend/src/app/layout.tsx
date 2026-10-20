import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "LocalGem Chat — Clon de Google Gemini 100% Local",
  description:
    "Asistente de IA multimodal 100% local y gratuito con FastAPI, SQLite, Ollama, voz bidireccional y modo de satisfacción A/B.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es" className="dark">
      <body className="bg-[#131314] text-[#e3e3e3] antialiased selection:bg-blue-500/30 selection:text-blue-200">
        {children}
      </body>
    </html>
  );
}
