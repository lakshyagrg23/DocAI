import * as TooltipPrimitive from '@radix-ui/react-tooltip'
import { Loader2 } from 'lucide-react'
import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { cn } from '@/lib/cn'

type Tone = 'ok' | 'warn' | 'clash' | 'calm' | 'accent'

const TONES: Record<Tone, string> = {
  ok: 'bg-ok-soft text-ok',
  warn: 'bg-warn-soft text-warn',
  clash: 'bg-clash-soft text-clash',
  calm: 'bg-calm-soft text-calm',
  accent: 'bg-accent-soft text-accent-ink',
}

export function Badge({ tone = 'calm', icon, children, className }: { tone?: Tone; icon?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium leading-5', TONES[tone], className)}>
      {icon}
      {children}
    </span>
  )
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost'
  size?: 'sm' | 'md' | 'icon'
  loading?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = 'secondary', size = 'md', loading, className, children, disabled, ...rest }, ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors disabled:pointer-events-none disabled:opacity-50',
        size === 'sm' && 'h-8 px-3 text-sm',
        size === 'md' && 'h-10 px-4 text-sm',
        size === 'icon' && 'h-9 w-9',
        variant === 'primary' && 'bg-accent text-white hover:bg-accent-ink dark:text-bg',
        variant === 'secondary' && 'border border-line bg-surface text-ink shadow-card hover:bg-sunken',
        variant === 'ghost' && 'text-muted hover:bg-sunken hover:text-ink',
        className,
      )}
      {...rest}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
      {children}
    </button>
  )
})

export function Tooltip({ content, children, side = 'top' }: { content: ReactNode; children: ReactNode; side?: 'top' | 'bottom' | 'left' | 'right' }) {
  return (
    <TooltipPrimitive.Root delayDuration={150}>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          side={side}
          sideOffset={6}
          className="z-50 max-w-xs rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink shadow-pop animate-fade-in"
        >
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  )
}

export const TooltipProvider = TooltipPrimitive.Provider

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('animate-pulse2 rounded-md bg-sunken', className)} aria-hidden />
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('rounded-xl border border-line bg-surface shadow-card', className)}>{children}</div>
}

export function Kicker({ children }: { children: ReactNode }) {
  return <p className="text-xs font-semibold uppercase tracking-wide text-muted">{children}</p>
}
