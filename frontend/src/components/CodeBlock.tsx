"use client";

import React, { useState } from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { Copy, Check } from "lucide-react";

export interface CodeBlockProps {
  language?: string;
  value: string;
}

export default function CodeBlock({ language, value }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const normalizedLanguage = (language || "text").toLowerCase().replace(/^language-/, "");
  const codeContent = value.replace(/\n$/, "");

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(codeContent);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback si clipboard API falla
      const textarea = document.createElement("textarea");
      textarea.value = codeContent;
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const lineCount = codeContent.split("\n").length;

  return (
    <div className="relative group my-3 rounded-2xl overflow-hidden border border-[#333537] bg-[#0d0e0f] shadow-lg">
      {/* Cabecera del bloque con lenguaje y botón copiar */}
      <div className="flex items-center justify-between px-4 py-1.5 bg-[#18191b] border-b border-[#333537]/80 text-xs">
        <span className="font-mono text-[11px] text-[#9aa0a6] uppercase tracking-wider">
          {normalizedLanguage}
        </span>

        <button
          type="button"
          onClick={handleCopy}
          title={copied ? "¡Copiado!" : "Copiar código"}
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-medium transition-all ${
            copied
              ? "bg-emerald-500/20 text-emerald-300 border border-emerald-500/40"
              : "text-[#9aa0a6] hover:text-white hover:bg-[#282a2c] border border-transparent"
          }`}
        >
          {copied ? (
            <>
              <Check className="w-3.5 h-3.5 text-emerald-400" />
              <span>¡Copiado!</span>
            </>
          ) : (
            <>
              <Copy className="w-3.5 h-3.5" />
              <span>Copiar</span>
            </>
          )}
        </button>
      </div>

      {/* Bloque con syntax highlighting */}
      <div className="overflow-x-auto text-[13px] font-mono leading-relaxed">
        <SyntaxHighlighter
          language={normalizedLanguage === "text" ? "bash" : normalizedLanguage}
          style={oneDark}
          customStyle={{
            margin: 0,
            padding: "1rem 1.1rem",
            background: "#0d0e0f",
            fontSize: "0.85rem",
          }}
          showLineNumbers={lineCount > 4}
          lineNumberStyle={{
            color: "#4e5154",
            paddingRight: "1rem",
            userSelect: "none",
          }}
          wrapLines={true}
        >
          {codeContent}
        </SyntaxHighlighter>
      </div>
    </div>
  );
}
