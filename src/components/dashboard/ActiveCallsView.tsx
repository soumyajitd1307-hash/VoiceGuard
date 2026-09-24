import React from 'react';
import { PhoneCall, ShieldAlert, Radio, User } from 'lucide-react';
import { useCallContext } from '../../context/CallContext';
import { CallDetails } from '../common/CallDetails';
import { ActiveCallTable } from '../common/ActiveCallTable';
import { LoadingState, ErrorState, EmptyState } from '../common/FeedbackStates';

export const ActiveCallsView: React.FC = () => {
  const { activeCalls, selectedCall, currentCallId, selectCall, openInvestigation, endCall, activeCallsStatus, callsError, refreshActiveCalls } = useCallContext();

  const current = selectedCall || activeCalls[0];
  const showLoading = activeCallsStatus === 'loading' && activeCalls.length === 0;
  const showError = activeCallsStatus === 'error' && activeCalls.length === 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div className="glass-panel" style={{ padding: '20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
          <h3 style={{ fontSize: '16px', fontWeight: 800, color: 'var(--text-main)' }}>
            Active WebRTC / VoIP Monitored Lines ({activeCalls.length})
          </h3>
          <button
            onClick={() => void refreshActiveCalls()}
            style={{
              background: 'transparent',
              border: '1px solid var(--border-subtle)',
              borderRadius: '6px',
              padding: '5px 12px',
              color: 'var(--text-muted)',
              fontSize: '11px',
              fontWeight: 700,
              cursor: 'pointer'
            }}
          >
            Refresh
          </button>
        </div>
        {showLoading ? (
          <LoadingState message="Loading active calls from Backend 4..." />
        ) : showError ? (
          <ErrorState
            title="Active calls unavailable"
            message={callsError || 'Could not reach Backend 4. No records were fabricated.'}
            onRetry={() => void refreshActiveCalls()}
          />
        ) : activeCalls.length === 0 ? (
          <EmptyState
            title="No active calls"
            message="Backend 4 reports no live sessions. Start a secure call from the mobile client."
          />
        ) : (
          <ActiveCallTable
            calls={activeCalls}
            selectedCallId={currentCallId}
            onSelectCall={selectCall}
            onInvestigateCall={openInvestigation}
          />
        )}
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
