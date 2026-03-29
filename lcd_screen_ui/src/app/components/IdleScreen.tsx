import { Brain, Wand2, Search, MessageSquareReply } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

interface IdleScreenProps {
  onActionSelect: (action: 'synthesis' | 'reformat' | 'search' | 'respond') => void;
}

const ACCENT = '#7aa2f7';

const BUTTONS: {
  id: 'synthesis' | 'reformat' | 'search' | 'respond';
  label: string;
  Icon: LucideIcon;
  thumb: string;
}[] = [
  {
    id: 'synthesis',
    label: 'SYNTHESIS',
    Icon: Brain,
    thumb: 'https://placehold.co/40x40/24283b/7aa2f7',
  },
  {
    id: 'reformat',
    label: 'REFORMAT',
    Icon: Wand2,
    thumb: 'https://placehold.co/40x40/24283b/7aa2f7',
  },
  {
    id: 'search',
    label: 'SEARCH',
    Icon: Search,
    thumb: 'https://placehold.co/40x40/24283b/7aa2f7',
  },
  {
    id: 'respond',
    label: 'RESPOND',
    Icon: MessageSquareReply,
    thumb: 'https://placehold.co/40x40/24283b/7aa2f7',
  },
];

/** Four L-shaped corner brackets, 8×8px each, inset 4px from button edges */
function CornerBrackets() {
  const base: React.CSSProperties = {
    position: 'absolute',
    width: 8,
    height: 8,
    opacity: 0.6,
    pointerEvents: 'none',
  };
  return (
    <>
      {/* top-left */}
      <div style={{ ...base, top: 4, left: 4, borderTop: `1px solid ${ACCENT}`, borderLeft: `1px solid ${ACCENT}` }} />
      {/* top-right */}
      <div style={{ ...base, top: 4, right: 4, borderTop: `1px solid ${ACCENT}`, borderRight: `1px solid ${ACCENT}` }} />
      {/* bottom-left */}
      <div style={{ ...base, bottom: 4, left: 4, borderBottom: `1px solid ${ACCENT}`, borderLeft: `1px solid ${ACCENT}` }} />
      {/* bottom-right */}
      <div style={{ ...base, bottom: 4, right: 4, borderBottom: `1px solid ${ACCENT}`, borderRight: `1px solid ${ACCENT}` }} />
    </>
  );
}

export function IdleScreen({ onActionSelect }: IdleScreenProps) {
  return (
    <div className="w-[320px] h-[240px] bg-[#1a1b26] text-white font-mono relative overflow-hidden">
      {/* Status Bar — 24px */}
      <div className="h-[24px] bg-[#24283b] border-b-2 border-[#7aa2f7] flex items-center justify-between px-3 text-[10px] font-semibold">
        <div className="flex items-center gap-2">
          <span className="text-[#7aa2f7]">SLACK: ACTIVE</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-2 h-2 rounded-full bg-[#10b981]" />
          <span className="text-[#10b981] text-[9px]">GATEKEEPER: OK</span>
        </div>
      </div>

      {/*
        2×2 Grid — p-2 gap-2:
          cell width  = (320 − 16px padding − 8px gap) / 2 = 148px
          cell height = (216 − 16px padding − 8px gap) / 2 = 96px
          content stack: 40px thumb + 4px + 32px icon + 4px + 14px label = 94px ✓
      */}
      <div className="grid grid-cols-2 grid-rows-2 gap-2 p-2 h-[216px]">
        {BUTTONS.map(({ id, label, Icon, thumb }) => (
          <button
            key={id}
            onClick={() => onActionSelect(id)}
            className="relative bg-[#24283b] border-2 border-[#7aa2f7] hover:bg-[#2f3449] active:bg-[#3d4263] transition-colors flex flex-col items-center justify-center gap-1 rounded-sm overflow-hidden"
          >
            <CornerBrackets />

            {/* 40×40 thumbnail — swap src for real PNG later */}
            <img
              src={thumb}
              alt=""
              width={40}
              height={40}
              style={{ borderRadius: 2, display: 'block', flexShrink: 0 }}
            />

            {/* Lucide icon — 32px, stroke 2.5, accent colour */}
            <Icon size={32} strokeWidth={2.5} color={ACCENT} />

            {/* Action label — JetBrains Mono 14px 700 tracking-wider */}
            <span
              style={{
                fontFamily: 'inherit',
                fontSize: 14,
                fontWeight: 700,
                letterSpacing: '0.1em',
                color: '#ffffff',
                lineHeight: 1,
              }}
            >
              {label}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
