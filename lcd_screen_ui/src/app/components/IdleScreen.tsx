import { Brain, Wand2, Search, MessageSquareReply } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

interface IdleScreenProps {
  onActionSelect: (action: 'synthesis' | 'reformat' | 'search' | 'respond') => void;
}

const ACCENT = '#7aa2f7';

const BUTTONS: {
  id: 'synthesis' | 'reformat' | 'search' | 'respond';
  physical: string;
  label: string;
  Icon: LucideIcon;
}[] = [
  {
    id: 'synthesis',
    physical: 'PB1',
    label: 'SYNTHESIS',
    Icon: Brain,
  },
  {
    id: 'reformat',
    physical: 'PB2',
    label: 'REFORMAT',
    Icon: Wand2,
  },
  {
    id: 'search',
    physical: 'PB3',
    label: 'SEARCH',
    Icon: Search,
  },
  {
    id: 'respond',
    physical: 'PB4',
    label: 'RESPOND',
    Icon: MessageSquareReply,
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
  const renderActionButton = ({ id, physical, label }: (typeof BUTTONS)[number]) => (
    <button
      key={id}
      onClick={() => onActionSelect(id)}
      className="relative bg-[#24283b] border-2 border-[#7aa2f7] hover:bg-[#2f3449] active:bg-[#3d4263] transition-colors flex items-center justify-center rounded-sm overflow-hidden px-2"
    >
      <CornerBrackets />
      <span className="text-[#7aa2f7] text-[9px] font-bold leading-none absolute top-1 left-2">
        {physical}
      </span>
      <span
        style={{
          fontFamily: 'inherit',
          fontSize: 13,
          fontWeight: 700,
          letterSpacing: 0,
          color: '#ffffff',
          lineHeight: 1,
          maxWidth: '100%',
          overflowWrap: 'anywhere',
          textAlign: 'center',
          whiteSpace: 'nowrap',
        }}
      >
        {label}
      </span>
    </button>
  );

  return (
    <div className="w-[320px] h-[240px] bg-[#1a1b26] text-white font-mono relative overflow-hidden">
      {/*
        Staggered bottom controls:
          top row: offset, PB2, PB4
          bottom row: PB1, PB3, offset
          total height: 96px = bottom 40% of the 320×240 LCD
      */}
      <div className="absolute left-2 bottom-0 h-[96px] w-[304px] grid grid-rows-2 gap-2">
        <div className="grid grid-cols-[58px_115px_115px] gap-2">
          <div className="relative bg-[#24283b] border-2 border-[#7aa2f7] rounded-sm opacity-60 overflow-hidden">
            <div className="absolute inset-0 bg-[repeating-linear-gradient(135deg,transparent_0,transparent_8px,#7aa2f7_9px,#7aa2f7_11px)] opacity-30" />
          </div>
          {renderActionButton(BUTTONS[1])}
          {renderActionButton(BUTTONS[3])}
        </div>
        <div className="grid grid-cols-[121px_109px_58px] gap-2">
          {renderActionButton(BUTTONS[0])}
          {renderActionButton(BUTTONS[2])}
          <div className="relative bg-[#24283b] border-2 border-[#7aa2f7] rounded-sm opacity-60 overflow-hidden">
            <div className="absolute inset-0 bg-[repeating-linear-gradient(135deg,transparent_0,transparent_8px,#7aa2f7_9px,#7aa2f7_11px)] opacity-30" />
          </div>
        </div>
      </div>
    </div>
  );
}
