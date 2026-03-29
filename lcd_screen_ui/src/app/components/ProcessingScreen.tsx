import { Loader2 } from 'lucide-react';

interface ProcessingScreenProps {
  action: 'synthesis' | 'reformat' | 'search' | 'respond';
}

const processingMessages = {
  synthesis: 'Synthesizing last 10 minutes...',
  reformat: 'Reformatting text...',
  search: 'Searching session...',
  respond: 'Drafting reply...',
};

export function ProcessingScreen({ action }: ProcessingScreenProps) {
  return (
    <div className="w-[320px] h-[240px] bg-[#1a1b26] text-white font-mono relative overflow-hidden flex flex-col items-center justify-center">
      <Loader2 size={48} className="text-[#7aa2f7] animate-spin mb-4" strokeWidth={2.5} />
      <p className="text-[14px] font-bold tracking-wider text-center px-4">
        {processingMessages[action]}
      </p>
      <div className="mt-6 flex gap-1">
        <div className="w-2 h-2 bg-[#7aa2f7] rounded-full animate-pulse"></div>
        <div className="w-2 h-2 bg-[#7aa2f7] rounded-full animate-pulse delay-100"></div>
        <div className="w-2 h-2 bg-[#7aa2f7] rounded-full animate-pulse delay-200"></div>
      </div>
    </div>
  );
}
