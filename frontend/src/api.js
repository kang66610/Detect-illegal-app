import axios from 'axios'

// Prevent a hung request from making the workbench look frozen forever.
// Long-running APK uploads override this timeout in DetectHome.
const api = axios.create({ baseURL: '/api', timeout: 30000 })
export default api
