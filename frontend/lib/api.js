import axios from 'axios'

const API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:5000'

// Create axios instance with default config
const api = axios.create({
  baseURL: API_BASE,
  timeout: 300000, // 5 minutes timeout for processing
  headers: {
    'Accept': 'application/json',
  }
})

api.interceptors.request.use(
  (config) => config,
  (error) => Promise.reject(error)
)

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 413) {
      throw new Error('File size too large. Please reduce file sizes or number of files.')
    }
    if (error.response?.status === 422) {
      throw new Error(
        'Invalid request or file format. Allowed types include PDF, DOCX, DOC, and TXT.'
      )
    }
    if (error.response?.status >= 500) {
      throw new Error('Server error. Please try again later.')
    }
    throw error
  }
)

/**
 * Process resumes with multiple AI algorithms
 * @param {Object} params - Processing parameters
 * @param {File[]} params.files - Resume files to process
 * @param {string} params.jobDescription - Job description text
 * @param {string} params.position - Position type
 * @param {string[]} params.methods - Array of algorithm IDs to use
 * @param {Object} params.options - Additional processing options
 * @returns {Promise<Object>} Processing results
 */
export async function processResumes({ 
  files, 
  jobDescription, 
  position, 
  methods, 
  options = {} 
}) {
  if (!files || files.length === 0) {
    throw new Error('No files provided for processing')
  }
  
  if (!jobDescription || jobDescription.trim().length === 0) {
    throw new Error('Job description is required')
  }
  
  if (!methods || methods.length === 0) {
    throw new Error('At least one algorithm must be selected')
  }

  const form = new FormData()
  
  // Add resume files
  files.forEach((file, index) => {
    form.append('resumes', file)
  })
  
  // Add job description
  form.append('jobDescription', jobDescription.trim())
  
  // Add position type
  form.append('position', position || 'general')
  
  // Add selected algorithms
  methods.forEach((method, index) => {
    form.append('methods', method)
  })
  
  // Add processing options
  form.append('options', JSON.stringify({
    includeExplanations: true,
    includeSkillExtraction: true,
    includeScoreBreakdown: true,
    combineResults: true,
    weightingStrategy: 'balanced', // balanced, accuracy_focused, speed_focused
    ...options
  }))
  
  // Add metadata
  form.append('metadata', JSON.stringify({
    timestamp: new Date().toISOString(),
    userAgent: navigator.userAgent,
    selectedMethodsCount: methods.length,
    filesCount: files.length,
    positionType: position
  }))

  try {
    const response = await api.post('/api/process-resumes', form, {
      headers: { 
        'Content-Type': 'multipart/form-data',
        'X-Processing-Methods': methods.join(','),
        'X-Files-Count': files.length.toString()
      },
      // Progress tracking
      onUploadProgress: (progressEvent) => {
        Math.round((progressEvent.loaded * 100) / progressEvent.total)
      }
    })
    
    return response.data
    
  } catch (error) {
    if (error.response?.data?.error) {
      throw new Error(error.response.data.error)
    }
    
    if (error.code === 'ECONNABORTED') {
      throw new Error('Processing timeout. Please try with fewer files or simpler algorithms.')
    }
    
    throw new Error(`Processing failed: ${error.message}`)
  }
}

/**
 * Get available job positions
 * @returns {Promise<Object[]>} Array of position objects
 */
export async function getPositions() {
  try {
    const response = await api.get('/api/positions')
    const data = response.data
    if (Array.isArray(data)) return data
    if (data && Array.isArray(data.positions)) return data.positions
    return []
  } catch (error) {
    // Return fallback positions if API fails
    return [
      { value: 'sde', label: 'Software Development Engineer', icon: '💻' },
      { value: 'swe', label: 'Software Engineer', icon: '⚙️' },
      { value: 'ml_engineer', label: 'ML Engineer', icon: '🤖' },
      { value: 'data_scientist', label: 'Data Scientist', icon: '📊' },
      { value: 'devops', label: 'DevOps Engineer', icon: '🔧' },
      { value: 'frontend', label: 'Frontend Developer', icon: '🎨' },
      { value: 'backend', label: 'Backend Developer', icon: '🗄️' },
      { value: 'fullstack', label: 'Full Stack Developer', icon: '🚀' },
      { value: 'general', label: 'General', icon: '📋' }
    ]
  }
}

/**
 * Get supported file formats and size limits
 * @returns {Promise<Object>} Format and limit information
 */
export async function getSupportedFormats() {
  try {
    const response = await api.get('/api/supported-formats')
    return response.data
  } catch (error) {
    // Return fallback format info
    return {
      formats: ['.pdf', '.docx', '.doc'],
      maxFileSize: 10485760, // 10MB
      maxFiles: 50,
      supportedMimeTypes: [
        'application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/msword'
      ]
    }
  }
}

/**
 * Get available algorithms and their information
 * @returns {Promise<Object[]>} Array of algorithm objects
 */
export async function getAvailableAlgorithms() {
  try {
    const response = await api.get('/api/algorithms')
    return response.data
  } catch (error) {
    // Mirrors backend `get_algorithm_status()` shape when offline
    return {
      available_algorithms: [
        'bert', 'distilbert', 'sbert',
        'xgboost', 'random_forest', 'svm', 'neural_network',
        'cosine', 'jaccard', 'ner'
      ],
      loaded_algorithms: [],
      algorithm_details: {}
    }
  }
}

/**
 * Get processing status for long-running jobs
 * @param {string} jobId - Processing job ID
 * @returns {Promise<Object>} Job status information
 */
export async function getProcessingStatus(jobId) {
  try {
    const response = await api.get(`/api/processing-status/${jobId}`)
    return response.data
  } catch (error) {
    const msg =
      error.response?.data?.error ||
      error.message ||
      'Failed to get processing status'
    throw new Error(msg)
  }
}

/**
 * Cancel a processing job
 * @param {string} jobId - Processing job ID
 * @returns {Promise<Object>} Cancellation result
 */
export async function cancelProcessing(jobId) {
  try {
    const response = await api.post(`/api/cancel-processing/${jobId}`)
    return response.data
  } catch (error) {
    const msg =
      error.response?.data?.error ||
      error.message ||
      'Failed to cancel processing'
    throw new Error(msg)
  }
}

/**
 * Validate files before processing
 * @param {File[]} files - Files to validate
 * @returns {Promise<Object>} Validation result
 */
export async function validateFiles(files) {
  const form = new FormData()
  files.forEach(file => form.append('files', file))
  
  try {
    const response = await api.post('/api/validate-files', form, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    return response.data
  } catch (error) {
    throw new Error('File validation failed')
  }
}

/**
 * Get system health and algorithm availability
 * @returns {Promise<Object>} System status
 */
export async function getSystemHealth() {
  try {
    const response = await api.get('/api/health')
    return response.data
  } catch (error) {
    return { status: 'unknown', algorithms: [], message: 'Unable to connect to server' }
  }
}

/**
 * Export results to different formats
 * @param {Object} results - Processing results
 * @param {string} format - Export format (csv, xlsx, json, pdf)
 * @returns {Promise<Blob>} Exported file blob
 */
export async function exportResults(results, format = 'csv') {
  try {
    const response = await api.post('/api/export-results', {
      results,
      format
    }, {
      responseType: 'blob'
    })
    return response.data
  } catch (error) {
    throw new Error('Failed to export results')
  }
}

/**
 * Get algorithm performance benchmarks
 * @returns {Promise<Object>} Performance data
 */
export async function getAlgorithmBenchmarks() {
  try {
    const response = await api.get('/v2/api/algorithm-benchmarks')
    return response.data
  } catch (error) {
    return null
  }
}
