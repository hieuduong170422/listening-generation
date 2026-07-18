'use client'

import { useStudio } from '@/lib/store'
import type { PartBrief } from '@/lib/types'

interface PartCardProps {
  part: PartBrief
  hasScript: boolean
  hasAudio: boolean
  isSelected: boolean
  isGeneratingScript: boolean
  isRenderingAudio: boolean
  onClick: () => void
}

function PartCard({
  part,
  hasScript,
  hasAudio,
  isSelected,
  isGeneratingScript,
  isRenderingAudio,
  onClick,
}: PartCardProps) {
  const busy = isGeneratingScript || isRenderingAudio

  let statusColor = 'var(--t3)'
  let statusLabel = 'Pending'
  if (hasAudio) { statusColor = 'var(--amber)'; statusLabel = 'Audio ready' }
  else if (hasScript) { statusColor = 'var(--ok)'; statusLabel = 'Script done' }
  else if (isRenderingAudio) { statusColor = 'var(--amber)'; statusLabel = 'Rendering…' }
  else if (isGeneratingScript) { statusColor = 'var(--accent)'; statusLabel = 'Writing…' }

  return (
    <button
      onClick={onClick}
      style={{
        textAlign: 'left',
        padding: '1rem',
        backgroundColor: isSelected ? 'var(--bg3)' : 'var(--bg2)',
        border: `1px solid ${isSelected ? 'var(--accent)' : 'var(--bd)'}`,
        borderRadius: '8px',
        cursor: 'pointer',
        transition: 'border-color 0.15s, background-color 0.15s',
        position: 'relative',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.5rem',
      }}
    >
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{
            width: '24px', height: '24px', borderRadius: '50%', flexShrink: 0,
            backgroundColor: isSelected ? 'var(--accent)' : 'var(--bg3)',
            border: `1px solid ${isSelected ? 'var(--accent)' : 'var(--bd)'}`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: '0.6875rem', fontWeight: 700,
            color: isSelected ? '#fff' : 'var(--t2)',
          }}>
            {part.index}
          </span>
          <span style={{
            fontSize: '0.875rem', fontWeight: 600, color: 'var(--t1)',
            lineHeight: 1.3,
          }}>
            {part.title}
          </span>
        </div>

        {/* Status badge */}
        <span style={{
          flexShrink: 0,
          fontSize: '0.625rem', fontWeight: 600, textTransform: 'uppercase',
          letterSpacing: '0.05em', color: statusColor,
          backgroundColor: `${statusColor}15`,
          border: `1px solid ${statusColor}40`,
          borderRadius: '4px', padding: '0.2rem 0.4rem',
          animation: busy ? 'pulse 1.5s ease-in-out infinite' : 'none',
        }}>
          {statusLabel}
        </span>
      </div>

      {/* Summary */}
      <p style={{
        fontSize: '0.75rem', color: 'var(--t2)', lineHeight: 1.5,
        display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
        overflow: 'hidden',
      }}>
        {part.summary}
      </p>

      {/* Key points preview */}
      {part.key_points.length > 0 && (
        <div style={{ display: 'flex', gap: '0.25rem', flexWrap: 'wrap' }}>
          {part.key_points.slice(0, 3).map((kp, i) => (
            <span key={i} style={{
              fontSize: '0.625rem', color: 'var(--t3)',
              backgroundColor: 'var(--bg1)',
              border: '1px solid var(--bd-s)',
              borderRadius: '3px', padding: '0.125rem 0.375rem',
            }}>
              {kp.length > 28 ? kp.slice(0, 28) + '…' : kp}
            </span>
          ))}
          {part.key_points.length > 3 && (
            <span style={{ fontSize: '0.625rem', color: 'var(--t3)', padding: '0.125rem 0.25rem' }}>
              +{part.key_points.length - 3}
            </span>
          )}
        </div>
      )}

      {/* Audio indicator */}
      {hasAudio && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: '0.375rem',
          fontSize: '0.6875rem', color: 'var(--amber)',
        }}>
          <span>▶</span>
          <span>Audio ready</span>
        </div>
      )}
    </button>
  )
}

export default function PartGrid() {
  const { state, dispatch } = useStudio()
  const { outline, scripts, audioIds, selectedPart, generatingScript, renderingAudio } = state

  if (!outline) return null

  function selectPart(idx: number) {
    dispatch({ type: 'SELECT_PART', partIndex: selectedPart === idx ? null : idx })
  }

  const totalParts = outline.parts.length
  const doneScripts = Object.keys(scripts).length
  const doneAudio = Object.keys(audioIds).length

  return (
    <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      {/* Outline header */}
      <div style={{
        padding: '1rem 1.25rem',
        borderBottom: '1px solid var(--bd)',
        backgroundColor: 'var(--bg1)',
        flexShrink: 0,
      }}>
        <h2 style={{
          fontSize: '1rem', fontWeight: 700, color: 'var(--t1)',
          marginBottom: '0.375rem', lineHeight: 1.3,
        }}>
          {outline.topic}
        </h2>
        <div style={{ display: 'flex', gap: '1rem', fontSize: '0.75rem', color: 'var(--t2)' }}>
          <span>{totalParts} parts · {outline.total_minutes} min</span>
          {doneScripts > 0 && (
            <span style={{ color: 'var(--ok)' }}>
              {doneScripts}/{totalParts} scripts
            </span>
          )}
          {doneAudio > 0 && (
            <span style={{ color: 'var(--amber)' }}>
              {doneAudio}/{totalParts} audio
            </span>
          )}
        </div>
      </div>

      {/* Parts grid */}
      <div style={{
        flex: 1, overflowY: 'auto', padding: '1rem',
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
        gap: '0.75rem',
        alignContent: 'start',
      }}>
        {outline.parts.map((part) => (
          <PartCard
            key={part.index}
            part={part}
            hasScript={Boolean(scripts[part.index])}
            hasAudio={Boolean(audioIds[part.index])}
            isSelected={selectedPart === part.index}
            isGeneratingScript={generatingScript === part.index}
            isRenderingAudio={renderingAudio === part.index}
            onClick={() => selectPart(part.index)}
          />
        ))}
      </div>
    </div>
  )
}
