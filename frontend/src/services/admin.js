import api from './api'

export const adminApi = {
  getUsers: (skip = 0, limit = 100) =>
    api.get('/admin/users', { params: { skip, limit } }).then(r => r.data),

  createUser: (payload) =>
    api.post('/admin/users', payload).then(r => r.data),

  updateUser: (userId, payload) =>
    api.patch(`/admin/users/${userId}`, payload).then(r => r.data),

  deleteUser: (userId) =>
    api.delete(`/admin/users/${userId}`),

  getIncidents: (skip = 0, limit = 100) =>
    api.get('/admin/incidents', { params: { skip, limit } }).then(r => r.data),

  deleteIncident: (incidentId) =>
    api.delete(`/admin/incidents/${incidentId}`),

  getPolicy: () =>
    api.get('/admin/policy').then(r => r.data).catch(err => {
      if (err.response?.status === 404) return null
      throw err
    }),

  uploadPolicy: (file) => {
    const form = new FormData()
    form.append('file', file)
    return api.post('/admin/policy', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }).then(r => r.data)
  },

  getSmtpTo: () =>
    api.get('/admin/config/smtp-to').then(r => r.data),

  setSmtpTo: (smtp_to) =>
    api.put('/admin/config/smtp-to', { smtp_to }).then(r => r.data),
}
