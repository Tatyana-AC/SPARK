import { CheckCircle2 } from 'lucide-react';
import { useEffect } from 'react';

interface SuccessScreenProps {
  action: 'synthesis' | 'reformat' | 'search' | 'respond';
  onComplete: () => void;
}

const successMessages = {
  synthesis: {
    title: 'SYNTHESIS COMPLETE',
    subtitle: 'Brief ready for review',
  },
  reformat: {
    title: 'TEXT REFORMATTED',
    subtitle: 'Changes applied',
  },
  search: {
    title: 'SEARCH COMPLETE',
    subtitle: '12 results found',
  },
  respond: {
    title: 'REPLY SENT',
    subtitle: 'Message delivered to Emily',
  },
};

export function SuccessScreen({ action, onComplete }: SuccessScreenProps) {
  const message = successMessages[action];

  useEffect(() => {
    const timer = setTimeout(() => {
      onComplete();
    }, 2000);

    return () => clearTimeout(timer);
  }, [onComplete]);

  return (
    <div className="w-[320px] h-[240px] bg-[#1a1b26] text-white font-mono relative overflow-hidden flex flex-col items-center justify-center">
      <CheckCircle2 size={64} className="text-[#10b981] mb-4" strokeWidth={2.5} />
      <h1 className="text-[16px] font-bold tracking-wider mb-2">
        {message.title}
      </h1>
      <p className="text-[14px] text-[#7aa2f7]">
        {message.subtitle}
      </p>
    </div>
  );
}
