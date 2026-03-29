interface ConfirmationScreenProps {
  action: 'synthesis' | 'reformat' | 'search' | 'respond';
  onConfirm: () => void;
  onCancel: () => void;
}

const confirmationMessages = {
  synthesis: {
    title: 'BRIEF ME ON LAST 10M?',
    context: 'Synthesis Requested',
  },
  reformat: {
    title: 'REWRITE HIGHLIGHTED TEXT?',
    context: 'Reformat Action',
  },
  search: {
    title: 'FIND KEYWORDS IN SESSION?',
    context: 'Search Query',
  },
  respond: {
    title: 'DRAFT REPLY TO SLACK?',
    context: 'Response to Emily',
  },
};

export function ConfirmationScreen({ action, onConfirm, onCancel }: ConfirmationScreenProps) {
  const message = confirmationMessages[action];

  return (
    <div className="w-[320px] h-[240px] bg-[#1a1b26] text-white font-mono relative overflow-hidden flex flex-col">
      {/* Top Half - Header */}
      <div className="flex-1 bg-[#24283b] border-b-2 border-[#7aa2f7] flex flex-col items-center justify-center px-4">
        <h1 className="text-[16px] font-bold tracking-wider mb-2 text-center leading-tight">
          {message.title}
        </h1>
        <p className="text-[14px] text-[#7aa2f7]">
          {message.context}
        </p>
      </div>

      {/* Bottom Half - Split Buttons */}
      <div className="flex h-[120px]">
        {/* Left: CONFIRM (Green) */}
        <button 
          onClick={onConfirm}
          className="flex-1 bg-[#10b981] border-2 border-[#059669] hover:bg-[#059669] active:bg-[#047857] transition-colors flex items-center justify-center font-bold text-[20px] tracking-widest"
        >
          CONFIRM
        </button>

        {/* Right: CANCEL (Red) */}
        <button 
          onClick={onCancel}
          className="flex-1 bg-[#dc2626] border-2 border-[#b91c1c] hover:bg-[#b91c1c] active:bg-[#991b1b] transition-colors flex items-center justify-center font-bold text-[20px] tracking-widest border-l-4 border-l-[#1a1b26]"
        >
          CANCEL
        </button>
      </div>
    </div>
  );
}