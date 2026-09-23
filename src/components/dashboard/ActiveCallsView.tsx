import React from 'react';
import { PhoneCall, ShieldAlert, Radio, User } from 'lucide-react';
import { useCallContext } from '../../context/CallContext';
import { CallDetails } from '../common/CallDetails';
import { ActiveCallTable } from '../common/ActiveCallTable';

export const ActiveCallsView: React.FC = () => {
  const { activeCalls, selectedCall, currentCallId, selectCall, openInvestigation, endCall } = useCallContext();

  const current = selectedCall || activeCalls[0];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div className="glass-panel" style={{ padding: '20px' }}>
        <h3 style={{ fontSize: '16px', fontWeight: 800, color: 'var(--text-main)', marginBottom: '14px' }}>
          Active WebRTC / VoIP Monitored Lines ({activeCalls.length})
        </h3>
        <ActiveCallTable
          calls={activeCalls}
          selectedCallId={currentCallId}
          onSelectCall={selectCall}
          onInvestigateCall={openInvestigation}
        />
      </div>

      {current && (
        <CallDetails
          call={current}
          onTerminateCall={() => endCall(current.id)}
          onOpenEvidence={() => openInvestigation(current)}
        />
      )}
    </div>
  );
};
