const waitForDesktopBridge = () => new Promise((resolve, reject) => {
  if (window.pywebview?.api?.call) {
    resolve(window.pywebview.api)
    return
  }
  let settled = false
  const finish = () => {
    if (settled) return
    settled = true
    if (window.pywebview?.api?.call) resolve(window.pywebview.api)
    else reject(new Error('pywebview bridge is unavailable'))
  }
  window.addEventListener('pywebviewready', finish, { once: true })
  window.setTimeout(finish, 5000)
})

export async function invoke(method, ...args) {
  const api = await waitForDesktopBridge()
  const response = await api.call(method, args, {})
  if (!response?.ok) {
    throw new Error(response?.error?.message || '后端操作失败')
  }
  return response.data
}
