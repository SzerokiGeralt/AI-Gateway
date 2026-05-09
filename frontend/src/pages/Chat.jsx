import { useState, useRef, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useAuth } from '../context/AuthContext'
import { streamChat } from '../services/api'

function UserIcon() {
  return (
    <div className="w-8 h-8 rounded-full bg-[#5d5d5d] flex items-center justify-center flex-shrink-0">
      <svg className="w-4 h-4 text-white" fill="currentColor" viewBox="0 0 24 24">
        <path d="M12 12c2.7 0 4.8-2.1 4.8-4.8S14.7 2.4 12 2.4 7.2 4.5 7.2 7.2 9.3 12 12 12zm0 2.4c-3.2 0-9.6 1.6-9.6 4.8v2.4h19.2v-2.4c0-3.2-6.4-4.8-9.6-4.8z"/>
      </svg>
    </div>
  )
}

function BotIcon() {
  return (
    <div className="w-8 h-8 rounded-full bg-white flex items-center justify-center flex-shrink-0">
      <svg className="w-4 h-4 text-[#212121]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
          d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
      </svg>
    </div>
  )
}

const THINKING_PHRASES = ['Myślę…', 'Analizuję…', 'Sprawdzam…', 'Przygotowuję odpowiedź…']

function ThinkingIndicator() {
  const [phase, setPhase] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setPhase(p => (p + 1) % THINKING_PHRASES.length), 1500)
    return () => clearInterval(id)
  }, [])
  return (
    <span className="text-gray-400 italic text-[15px] transition-all duration-300">
      {THINKING_PHRASES[phase]}
    </span>
  )
}

function Message({ msg, isStreaming }) {
  const isUser = msg.role === 'user'
  const showThinking = !isUser && isStreaming && !msg.content
  return (
    <div className={`py-5 px-4 ${isUser ? '' : 'bg-[#2a2a2a]'}`}>
      <div className="max-w-3xl mx-auto flex gap-4">
        {isUser ? <UserIcon /> : <BotIcon />}
        <div className="flex-1 min-w-0 pt-1">
          <p className={`text-sm font-semibold mb-1 ${isUser ? 'text-gray-300' : 'text-white'}`}>
            {isUser ? 'Ty' : 'AI Gateway'}
          </p>
          {isUser ? (
            <div className="message-content text-[15px] leading-relaxed text-gray-100">
              {msg.content || <span className="text-gray-500 italic">Brak treści</span>}
            </div>
          ) : showThinking ? (
            <ThinkingIndicator />
          ) : (
            <div className={`markdown-content text-[15px] text-gray-100 ${isStreaming ? 'streaming-cursor' : ''}`}>
              {msg.content ? (
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
              ) : (
                <span className="text-gray-500 italic">Brak treści</span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center text-center px-4">
      <div className="w-16 h-16 rounded-full bg-white/10 flex items-center justify-center mb-4">
        <svg className="w-8 h-8 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
            d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
        </svg>
      </div>
      <h2 className="text-xl font-semibold text-white mb-2">Jak mogę Ci pomóc?</h2>
      <p className="text-sm text-gray-500 max-w-xs">
        Zadaj pytanie lub rozpocznij rozmowę. Każda wiadomość jest chroniona przez filtr DLP.
      </p>
    </div>
  )
}

export default function Chat() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [error, setError] = useState('')
  const bottomRef = useRef(null)
  const textareaRef = useRef(null)
  const abortRef = useRef(false)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleNewChat = useCallback(() => {
    if (isStreaming) return
    setMessages([])
    setError('')
    textareaRef.current?.focus()
  }, [isStreaming])

  const handleSend = useCallback(async () => {
    const text = input.trim()
    if (!text || isStreaming) return
    setError('')
    setInput('')

    const userMsg = { role: 'user', content: text }
    const nextMessages = [...messages, userMsg]
    const assistantPlaceholder = { role: 'assistant', content: '' }
    setMessages([...nextMessages, assistantPlaceholder])
    setIsStreaming(true)
    abortRef.current = false

    await streamChat(
      nextMessages,
      (chunk) => {
        if (abortRef.current) return
        setMessages(prev => {
          const updated = [...prev]
          updated[updated.length - 1] = {
            ...updated[updated.length - 1],
            content: updated[updated.length - 1].content + chunk,
          }
          return updated
        })
      },
      () => {
        setIsStreaming(false)
      },
      (errMsg) => {
        setIsStreaming(false)
        setMessages(prev => prev.slice(0, -1))
        setError(errMsg)
      }
    )
  }, [input, messages, isStreaming])

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  // Auto-grow textarea
  const handleInput = (e) => {
    const el = e.target
    setInput(el.value)
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 200) + 'px'
  }

  return (
    <div className="flex h-screen bg-[#212121] overflow-hidden">
      {/* Sidebar */}
      <aside className="w-64 bg-[#171717] flex flex-col flex-shrink-0">
        <div className="p-3">
          <button
            onClick={handleNewChat}
            disabled={isStreaming}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-gray-300
                       hover:bg-white/10 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            Nowa rozmowa
          </button>
        </div>

        <div className="flex-1" />

        {/* Admin link */}
        {user?.role === 'ADMIN' && (
          <div className="px-3 pb-2">
            <button
              onClick={() => navigate('/admin')}
              className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-amber-400
                         hover:bg-white/10 transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
              Panel Admina
            </button>
          </div>
        )}

        {/* User info + logout */}
        <div className="border-t border-white/10 p-3">
          <div className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-white/10 transition-colors group">
            <div className="w-7 h-7 rounded-full bg-[#5d5d5d] flex items-center justify-center flex-shrink-0">
              <span className="text-xs font-semibold text-white uppercase">
                {user?.username?.[0] ?? '?'}
              </span>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm text-white truncate">{user?.username}</p>
              {user?.department && (
                <p className="text-xs text-gray-500 truncate">{user.department}</p>
              )}
            </div>
            <button
              onClick={handleLogout}
              title="Wyloguj"
              className="text-gray-500 hover:text-white transition-colors opacity-0 group-hover:opacity-100"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
              </svg>
            </button>
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 flex flex-col overflow-hidden relative">
        {messages.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <EmptyState />
          </div>
        )}
        {/* Messages */}
        <div className="flex-1 overflow-y-auto">
          {messages.length > 0 && (
            <div>
              {messages.map((msg, i) => (
                <Message
                  key={i}
                  msg={msg}
                  isStreaming={isStreaming && i === messages.length - 1 && msg.role === 'assistant'}
                />
              ))}
              <div ref={bottomRef} className="h-8" />
            </div>
          )}
        </div>

        {/* Input area */}
        <div className="px-4 pb-6 pt-2">
          {error && (
            <div className="max-w-3xl mx-auto mb-3 bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-2.5 text-sm text-red-400 flex items-center gap-2">
              <svg className="w-4 h-4 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
              </svg>
              {error}
            </div>
          )}
          <div className="max-w-3xl mx-auto">
            <div className="relative bg-[#2f2f2f] rounded-2xl border border-white/10 focus-within:border-white/20 transition-colors">
              <textarea
                ref={textareaRef}
                value={input}
                onInput={handleInput}
                onChange={() => {}}
                onKeyDown={handleKeyDown}
                disabled={isStreaming}
                rows={1}
                placeholder="Wyślij wiadomość…"
                className="w-full bg-transparent text-white placeholder-gray-500 resize-none
                           px-4 py-3.5 pr-24 text-[15px] leading-relaxed
                           focus:outline-none disabled:opacity-50"
                style={{ maxHeight: '200px', overflowY: 'auto' }}
              />
              {/* Przycisk wyślij */}
              <button
                onClick={handleSend}
                disabled={!input.trim() || isStreaming}
                className="absolute right-3 bottom-3 w-8 h-8 flex items-center justify-center
                           rounded-lg bg-white text-[#212121] disabled:bg-gray-600 disabled:text-gray-400
                           hover:bg-gray-100 disabled:cursor-not-allowed transition-colors"
              >
                {isStreaming ? (
                  <span className="w-3 h-3 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" />
                ) : (
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 12h14M12 5l7 7-7 7" />
                  </svg>
                )}
              </button>
            </div>
            <p className="text-center text-xs text-gray-600 mt-2">
              Wiadomości są filtrowane przez DLP. Shift+Enter = nowa linia.
            </p>
          </div>
        </div>
      </main>
    </div>
  )
}
