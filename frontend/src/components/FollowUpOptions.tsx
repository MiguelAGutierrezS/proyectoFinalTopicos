"use client";

import React from "react";
import { Sparkles, ArrowUpRight } from "lucide-react";

export interface FollowUpOptionsProps {
  options: string[];
  onSelectOption: (optionText: string) => void;
  disabled?: boolean;
}

export default function FollowUpOptions({
  options,
  onSelectOption,
  disabled = false,
}: FollowUpOptionsProps) {
  if (!options || options.length === 0) {
    return null;
  }

  return (
    <div className="mt-3 pt-2.5 border-t border-[#333537]/50">
      <div className="flex items-center gap-1.5 text-[11px] font-medium text-[#9aa0a6] mb-2">
        <Sparkles className="w-3.5 h-3.5 text-[#4b90ff]" />
        <span>Opciones sugeridas para continuar:</span>
      </div>

      <div className="flex flex-wrap gap-2">
        {options.map((option, idx) => (
          <button
            key={`${idx}-${option}`}
            type="button"
            disabled={disabled}
            onClick={() => onSelectOption(option)}
            className="group inline-flex items-center gap-1.5 text-left text-xs sm:text-[13px] px-3.5 py-2 rounded-2xl bg-[#1e1f20] hover:bg-gradient-to-r hover:from-[#4b90ff]/20 hover:to-[#a855f7]/20 text-[#e3e3e3] hover:text-white border border-[#333537] hover:border-[#4b90ff]/60 disabled:opacity-50 disabled:pointer-events-none transition-all duration-150 shadow-sm"
          >
            <span>{option}</span>
            <ArrowUpRight className="w-3.5 h-3.5 text-[#9aa0a6] group-hover:text-[#4b90ff] group-hover:translate-x-0.5 group-hover:-translate-y-0.5 transition-transform shrink-0" />
          </button>
        ))}
      </div>
    </div>
  );
}
