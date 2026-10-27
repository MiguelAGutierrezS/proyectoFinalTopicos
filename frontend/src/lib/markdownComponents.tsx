import React from "react";
import CodeBlock from "@/components/CodeBlock";
import type { Components } from "react-markdown";

/**
 * Componentes compartidos para ReactMarkdown con Syntax Highlighting en bloques de código
 * y soporte completo de estilo Google Gemini para tablas, enlaces y código en línea.
 */
export const geminiMarkdownComponents: Components = {
  code({ className, children, ...props }) {
    const match = /language-(\w+)/.exec(className || "");
    const codeString = String(children || "").replace(/\n$/, "");
    const isMultiline = codeString.includes("\n");

    // Si es un bloque con lenguaje declarado o con saltos de línea -> CodeBlock con resaltado y botón Copiar
    if (match || isMultiline) {
      return (
        <CodeBlock
          language={match ? match[1] : undefined}
          value={codeString}
        />
      );
    }

    // Código inline simple `ejemplo`
    return (
      <code
        className="bg-[#282a2c] text-[#a8c7fa] px-1.5 py-0.5 rounded text-[0.875em] font-mono border border-[#3c4043]"
        {...props}
      >
        {children}
      </code>
    );
  },
  a({ href, children, ...props }) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-[#8ab4f8] hover:text-[#aecbfa] underline underline-offset-2 transition-colors"
        {...props}
      >
        {children}
      </a>
    );
  },
};
