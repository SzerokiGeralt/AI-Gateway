import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { adminApi } from '../services/admin'
import Modal from '../components/Modal'

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmtDate(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('pl-PL', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function Badge({ role }) {
  const cls = role === 'ADMIN'
    ? 'bg-amber-500/20 text-amber-400 border-amber-500/30'
    : 'bg-blue-500/20 text-blue-400 border-blue-500/30'
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium border ${cls}`}>
      {role}
    </span>
  )
}

function Spinner() {
  return <span className="w-5 h-5 border-2 border-white/20 border-t-white rounded-full animate-spin inline-block" />
}

// ─── User Form ─────────────────────────────────────────────────────────────────

const EMPTY_USER_FORM = { username: '', password: '', role: 'USER', department: '' }

function UserForm({ initial, onSubmit, loading, error, isEdit }) {
  const [form, setForm] = useState(initial || EMPTY_USER_FORM)
  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const handleSubmit = (e) => {
    e.preventDefault()
    onSubmit(form)
  }

  const inputCls = `w-full bg-[#212121] border border-white/10 rounded-lg px-3 py-2 text-sm text-white
    placeholder-gray-500 focus:outline-none focus:border-white/30 transition-colors`

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {!isEdit && (
        <div>
          <label className="block text-xs text-gray-400 mb-1">Nazwa użytkownika *</label>
          <input
            required
            value={form.username}
            onChange={e => set('username', e.target.value)}
            className={inputCls}
            placeholder="jan.kowalski"
          />
        </div>
      )}
      <div>
        <label className="block text-xs text-gray-400 mb-1">
          {isEdit ? 'Nowe hasło (zostaw puste, aby nie zmieniać)' : 'Hasło *'}
        </label>
        <input
          type="password"
          required={!isEdit}
          value={form.password}
          onChange={e => set('password', e.target.value)}
          className={inputCls}
          placeholder="••••••••"
        />
      </div>
      <div>
        <label className="block text-xs text-gray-400 mb-1">Rola</label>
        <select
          value={form.role}
          onChange={e => set('role', e.target.value)}
          className={inputCls}
        >
          <option value="USER">USER</option>
          <option value="ADMIN">ADMIN</option>
        </select>
      </div>
      <div>
        <label className="block text-xs text-gray-400 mb-1">Dział (opcjonalnie)</label>
        <input
          value={form.department}
          onChange={e => set('department', e.target.value)}
          className={inputCls}
          placeholder="IT / HR / Finanse…"
        />
      </div>
      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2 text-sm text-red-400">
          {error}
        </div>
      )}
      <button
        type="submit"
        disabled={loading}
        className="w-full bg-white text-[#212121] font-semibold rounded-lg py-2.5 text-sm
                   hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex items-center justify-center gap-2"
      >
        {loading && <Spinner />}
        {isEdit ? 'Zapisz zmiany' : 'Utwórz użytkownika'}
      </button>
    </form>
  )
}

// ─── Users Panel ──────────────────────────────────────────────────────────────

function UsersPanel({ currentUser }) {
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [createOpen, setCreateOpen] = useState(false)
  const [editUser, setEditUser] = useState(null)
  const [deleteUser, setDeleteUser] = useState(null)
  const [formLoading, setFormLoading] = useState(false)
  const [formError, setFormError] = useState('')
  const [deleteLoading, setDeleteLoading] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    adminApi.getUsers()
      .then(setUsers)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  const handleCreate = async (form) => {
    setFormLoading(true)
    setFormError('')
    try {
      const payload = {
        username: form.username,
        password: form.password,
        role: form.role,
        department: form.department || null,
      }
      await adminApi.createUser(payload)
      setCreateOpen(false)
      load()
    } catch (err) {
      const detail = err?.response?.data?.detail
      if (Array.isArray(detail)) {
        setFormError(detail.map(d => d.msg).join(', '))
      } else {
        setFormError(typeof detail === 'string' ? detail : 'Błąd podczas tworzenia użytkownika.')
      }
    } finally {
      setFormLoading(false)
    }
  }

  const handleEdit = async (form) => {
    setFormLoading(true)
    setFormError('')
    try {
      const payload = {
        role: form.role,
        department: form.department || null,
      }
      if (form.password) payload.password = form.password
      await adminApi.updateUser(editUser.id, payload)
      setEditUser(null)
      load()
    } catch (err) {
      const detail = err?.response?.data?.detail
      setFormError(typeof detail === 'string' ? detail : 'Błąd podczas edycji.')
    } finally {
      setFormLoading(false)
    }
  }

  const handleDelete = async () => {
    if (!deleteUser) return
    setDeleteLoading(true)
    try {
      await adminApi.deleteUser(deleteUser.id)
      setDeleteUser(null)
      load()
    } catch (err) {
      alert(err?.response?.data?.detail || 'Błąd podczas usuwania.')
    } finally {
      setDeleteLoading(false)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="text-lg font-semibold text-white">Użytkownicy</h2>
          <p className="text-sm text-gray-500 mt-0.5">{users.length} kont w systemie</p>
        </div>
        <button
          onClick={() => { setCreateOpen(true); setFormError('') }}
          className="flex items-center gap-2 bg-white text-[#212121] font-semibold text-sm rounded-lg px-4 py-2
                     hover:bg-gray-100 transition-colors"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          Dodaj użytkownika
        </button>
      </div>

      {loading ? (
        <div className="flex justify-center py-16"><Spinner /></div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-white/10">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/10 bg-white/5">
                <th className="text-left px-4 py-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Użytkownik</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Rola</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Dział</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Utworzono</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {users.map(u => (
                <tr key={u.id} className="hover:bg-white/5 transition-colors">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <div className="w-7 h-7 rounded-full bg-[#5d5d5d] flex items-center justify-center flex-shrink-0">
                        <span className="text-xs font-semibold text-white uppercase">{u.username[0]}</span>
                      </div>
                      <div>
                        <p className="text-white font-medium">{u.username}</p>
                        <p className="text-gray-500 text-xs font-mono">{u.id.slice(0, 8)}…</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3"><Badge role={u.role} /></td>
                  <td className="px-4 py-3 text-gray-400">{u.department || '—'}</td>
                  <td className="px-4 py-3 text-gray-500">{fmtDate(u.created_at)}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2 justify-end">
                      <button
                        onClick={() => { setEditUser(u); setFormError('') }}
                        className="text-gray-400 hover:text-white transition-colors p-1 rounded hover:bg-white/10"
                        title="Edytuj"
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                        </svg>
                      </button>
                      <button
                        onClick={() => setDeleteUser(u)}
                        disabled={u.id === currentUser?.id}
                        className="text-gray-400 hover:text-red-400 transition-colors p-1 rounded hover:bg-red-500/10
                                   disabled:opacity-30 disabled:cursor-not-allowed"
                        title={u.id === currentUser?.id ? 'Nie możesz usunąć własnego konta' : 'Usuń'}
                      >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                            d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {users.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-10 text-center text-gray-500">Brak użytkowników</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Create modal */}
      <Modal isOpen={createOpen} onClose={() => setCreateOpen(false)} title="Nowy użytkownik">
        <UserForm
          onSubmit={handleCreate}
          loading={formLoading}
          error={formError}
          isEdit={false}
        />
      </Modal>

      {/* Edit modal */}
      <Modal isOpen={!!editUser} onClose={() => setEditUser(null)} title="Edytuj użytkownika">
        {editUser && (
          <UserForm
            initial={{ username: editUser.username, password: '', role: editUser.role, department: editUser.department || '' }}
            onSubmit={handleEdit}
            loading={formLoading}
            error={formError}
            isEdit
          />
        )}
      </Modal>

      {/* Delete confirm modal */}
      <Modal isOpen={!!deleteUser} onClose={() => setDeleteUser(null)} title="Usuń użytkownika">
        {deleteUser && (
          <div>
            <p className="text-gray-300 text-sm mb-5">
              Czy na pewno chcesz usunąć konto <span className="font-semibold text-white">{deleteUser.username}</span>?
              Tej operacji nie można cofnąć.
            </p>
            <div className="flex gap-3">
              <button
                onClick={() => setDeleteUser(null)}
                className="flex-1 bg-white/10 text-white rounded-lg py-2.5 text-sm hover:bg-white/20 transition-colors"
              >
                Anuluj
              </button>
              <button
                onClick={handleDelete}
                disabled={deleteLoading}
                className="flex-1 bg-red-600 text-white rounded-lg py-2.5 text-sm font-semibold
                           hover:bg-red-700 disabled:opacity-50 transition-colors flex items-center justify-center gap-2"
              >
                {deleteLoading && <Spinner />}
                Usuń
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  )
}

// ─── Incidents Panel ───────────────────────────────────────────────────────────

function IncidentRow({ inc, users }) {
  const [expanded, setExpanded] = useState(false)
  const username = users?.[inc.user_id] || inc.user_id?.slice(0, 8) + '…'

  return (
    <>
      <tr
        className="hover:bg-white/5 transition-colors cursor-pointer"
        onClick={() => setExpanded(x => !x)}
      >
        <td className="px-4 py-3 text-gray-400 text-xs">{fmtDate(inc.created_at)}</td>
        <td className="px-4 py-3">
          <span className="text-gray-300 font-mono text-xs">{username}</span>
        </td>
        <td className="px-4 py-3">
          <span className="text-red-400 text-sm line-clamp-1">{inc.reason}</span>
        </td>
        <td className="px-4 py-3 text-gray-500 text-xs max-w-[220px] truncate">
          {inc.original_prompt}
        </td>
        <td className="px-4 py-3">
          <svg
            className={`w-4 h-4 text-gray-500 transition-transform ${expanded ? 'rotate-180' : ''}`}
            fill="none" stroke="currentColor" viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </td>
      </tr>
      {expanded && (
        <tr className="bg-[#1a1a1a]">
          <td colSpan={5} className="px-6 py-4">
            <div className="grid grid-cols-1 gap-4 text-sm">
              <div>
                <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Oryginalny prompt</p>
                <p className="text-gray-300 bg-red-500/5 border border-red-500/20 rounded-lg p-3 message-content">
                  {inc.original_prompt}
                </p>
              </div>
              <div>
                <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Wersja zanonimizowana (po DLP)</p>
                <p className="text-gray-300 bg-green-500/5 border border-green-500/20 rounded-lg p-3 message-content">
                  {inc.sanitized_prompt || '—'}
                </p>
              </div>
              <div>
                <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Powód blokady</p>
                <p className="text-amber-300 text-sm">{inc.reason}</p>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  )
}

function IncidentsPanel() {
  const [incidents, setIncidents] = useState([])
  const [users, setUsers] = useState({})
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      adminApi.getIncidents(),
      adminApi.getUsers(),
    ]).then(([incs, usrs]) => {
      setIncidents(incs)
      const map = {}
      usrs.forEach(u => { map[u.id] = u.username })
      setUsers(map)
    }).catch(() => {}).finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <div className="mb-5">
        <h2 className="text-lg font-semibold text-white">Logi DLP — Incydenty bezpieczeństwa</h2>
        <p className="text-sm text-gray-500 mt-0.5">
          {incidents.length} zarejestrowanych incydentów. Kliknij wiersz, aby zobaczyć szczegóły.
        </p>
      </div>

      {loading ? (
        <div className="flex justify-center py-16"><Spinner /></div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-white/10">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-white/10 bg-white/5">
                <th className="text-left px-4 py-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Data</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Użytkownik</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Powód blokady</th>
                <th className="text-left px-4 py-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Prompt (fragment)</th>
                <th className="px-4 py-3 w-8" />
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {incidents.map(inc => (
                <IncidentRow key={inc.id} inc={inc} users={users} />
              ))}
              {incidents.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-10 text-center text-gray-500">
                    Brak zarejestrowanych incydentów
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

// ─── Policy Panel ──────────────────────────────────────────────────────────────

function PolicyPanel() {
  const [file, setFile] = useState(null)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [currentPolicy, setCurrentPolicy] = useState(undefined) // undefined = loading

  useEffect(() => {
    adminApi.getPolicy()
      .then(data => setCurrentPolicy(data))
      .catch(() => setCurrentPolicy(null))
  }, [])

  const handleUpload = async (e) => {
    e.preventDefault()
    if (!file) return
    setLoading(true)
    setError('')
    setResult(null)
    try {
      const data = await adminApi.uploadPolicy(file)
      setResult(data)
      setCurrentPolicy(data)
      setFile(null)
    } catch (err) {
      setError(err?.response?.data?.detail || 'Błąd podczas przesyłania pliku.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <div className="mb-5">
        <h2 className="text-lg font-semibold text-white">Polityka DLP</h2>
        <p className="text-sm text-gray-500 mt-0.5">Prześlij plik .txt z polityką firmową dla filtra DLP.</p>
      </div>

      {/* Status aktualnej polityki */}
      <div className="mb-5">
        {currentPolicy === undefined ? (
          <div className="flex items-center gap-2 text-sm text-gray-500">
            <Spinner />
            <span>Sprawdzanie statusu polityki…</span>
          </div>
        ) : currentPolicy ? (
          <div className="inline-flex items-center gap-2 bg-green-500/10 border border-green-500/20 rounded-lg px-4 py-2">
            <svg className="w-4 h-4 text-green-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <span className="text-sm text-green-400">
              Ostatnia aktualizacja: <span className="font-semibold">{fmtDate(currentPolicy.updated_at)}</span>
            </span>
          </div>
        ) : (
          <div className="inline-flex items-center gap-2 bg-amber-500/10 border border-amber-500/20 rounded-lg px-4 py-2">
            <svg className="w-4 h-4 text-amber-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
            </svg>
            <span className="text-sm text-amber-400">Polityka nie została jeszcze ustalona</span>
          </div>
        )}
      </div>

      <div className="max-w-lg">
        <form onSubmit={handleUpload} className="space-y-4">
          <div
            className="border-2 border-dashed border-white/20 rounded-xl p-8 text-center hover:border-white/40 transition-colors cursor-pointer"
            onClick={() => document.getElementById('policy-file').click()}
          >
            <svg className="w-10 h-10 text-gray-500 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <p className="text-gray-400 text-sm">
              {file ? (
                <span className="text-white font-medium">{file.name}</span>
              ) : (
                <>Kliknij, aby wybrać plik <span className="text-white font-medium">.txt</span></>
              )}
            </p>
            <input
              id="policy-file"
              type="file"
              accept=".txt"
              className="hidden"
              onChange={e => setFile(e.target.files?.[0] || null)}
            />
          </div>
          {error && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-2.5 text-sm text-red-400">
              {error}
            </div>
          )}
          {result && (
            <div className="bg-green-500/10 border border-green-500/30 rounded-lg px-4 py-2.5 text-sm text-green-400">
              Polityka przesłana pomyślnie. ID: <span className="font-mono">{result.id?.slice(0, 8)}…</span>
            </div>
          )}
          <button
            type="submit"
            disabled={!file || loading}
            className="flex items-center gap-2 bg-white text-[#212121] font-semibold text-sm rounded-lg px-5 py-2.5
                       hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading && <Spinner />}
            Prześlij politykę
          </button>
        </form>
      </div>
    </div>
  )
}

// ─── Email Config Panel ────────────────────────────────────────────────────────

function EmailConfigPanel() {
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [success, setSuccess] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    adminApi.getSmtpTo()
      .then(data => setEmail(data.smtp_to || ''))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const handleSave = async (e) => {
    e.preventDefault()
    setSaving(true)
    setSuccess(false)
    setError('')
    try {
      await adminApi.setSmtpTo(email)
      setSuccess(true)
      setTimeout(() => setSuccess(false), 4000)
    } catch (err) {
      const detail = err?.response?.data?.detail
      if (Array.isArray(detail)) {
        setError(detail.map(d => d.msg).join(', '))
      } else {
        setError(typeof detail === 'string' ? detail : 'Błąd podczas zapisywania.')
      }
    } finally {
      setSaving(false)
    }
  }

  const inputCls = `w-full bg-[#212121] border border-white/10 rounded-lg px-3 py-2.5 text-sm text-white
    placeholder-gray-500 focus:outline-none focus:border-white/30 transition-colors`

  return (
    <div>
      <div className="mb-5">
        <h2 className="text-lg font-semibold text-white">Konfiguracja poczty</h2>
        <p className="text-sm text-gray-500 mt-0.5">
          Adres email odbiorcy powiadomień o incydentach DLP. Nadpisuje domyślny adres z konfiguracji serwera.
        </p>
      </div>
      <div className="max-w-lg">
        {loading ? (
          <div className="flex justify-center py-10"><Spinner /></div>
        ) : (
          <form onSubmit={handleSave} className="space-y-4">
            <div>
              <label className="block text-xs text-gray-400 mb-1.5">Adres email odbiorcy alertów DLP</label>
              <input
                type="email"
                required
                value={email}
                onChange={e => { setEmail(e.target.value); setSuccess(false) }}
                className={inputCls}
                placeholder="security@firma.pl"
              />
              <p className="mt-1.5 text-xs text-gray-600">
                Na ten adres wysyłane są powiadomienia o każdym wykrytym naruszeniu polityki.
              </p>
            </div>

            {success && (
              <div className="flex items-center gap-2 bg-green-500/10 border border-green-500/30 rounded-lg px-4 py-2.5 text-sm text-green-400">
                <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                Adres email zapisany pomyślnie.
              </div>
            )}
            {error && (
              <div className="bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-2.5 text-sm text-red-400">
                {error}
              </div>
            )}
            <button
              type="submit"
              disabled={saving}
              className="flex items-center gap-2 bg-white text-[#212121] font-semibold text-sm rounded-lg px-5 py-2.5
                         hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {saving && <Spinner />}
              Zapisz adres
            </button>
          </form>
        )}
      </div>
    </div>
  )
}

// ─── Admin Page ────────────────────────────────────────────────────────────────

const TABS = [
  { id: 'users', label: 'Użytkownicy', icon: 'M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z' },
  { id: 'incidents', label: 'Incydenty DLP', icon: 'M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z' },
  { id: 'policy', label: 'Polityka DLP', icon: 'M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z' },
  { id: 'email', label: 'Konfiguracja poczty', icon: 'M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z' },
]

export default function Admin() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [tab, setTab] = useState('users')

  const handleLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="flex h-screen bg-[#212121] overflow-hidden">
      {/* Sidebar */}
      <aside className="w-60 bg-[#171717] flex flex-col flex-shrink-0">
        <div className="p-4 border-b border-white/10">
          <h1 className="text-sm font-semibold text-white">AI Gateway</h1>
          <p className="text-xs text-amber-400 mt-0.5">Panel Administratora</p>
        </div>

        <nav className="p-3 space-y-1 flex-1">
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors text-left
                ${tab === t.id
                  ? 'bg-white/10 text-white font-medium'
                  : 'text-gray-400 hover:bg-white/5 hover:text-gray-200'
                }`}
            >
              <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={t.icon} />
              </svg>
              {t.label}
            </button>
          ))}
        </nav>

        <div className="border-t border-white/10 p-3 space-y-1">
          <button
            onClick={() => navigate('/chat')}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-gray-400 hover:bg-white/5 hover:text-gray-200 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
            </svg>
            Przejdź do czatu
          </button>
          <button
            onClick={handleLogout}
            className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm text-gray-400 hover:bg-white/5 hover:text-red-400 transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
            </svg>
            Wyloguj
          </button>
        </div>

        <div className="px-4 py-3 border-t border-white/10">
          <p className="text-xs text-gray-600 truncate">{user?.username}</p>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto p-6">
        {tab === 'users' && <UsersPanel currentUser={user} />}
        {tab === 'incidents' && <IncidentsPanel />}
        {tab === 'policy' && <PolicyPanel />}
        {tab === 'email' && <EmailConfigPanel />}
      </main>
    </div>
  )
}
