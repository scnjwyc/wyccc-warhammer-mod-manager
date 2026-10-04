// Drag hover changes only the insertion marker, never the reactive MOD list.
export const createDragFeedback = (getRoot, getEndMarker) => {
  let target = null
  let placement = ''
  let source = null
  let atEnd = false
  const clearPreview = () => {
    target?.classList.remove('drop-before', 'drop-after')
    target = null
    placement = ''
    atEnd = false
    if (getEndMarker()) getEndMarker().hidden = true
  }
  const clearSource = () => {
    source?.classList.remove('dragging')
    source = null
  }
  return {
    showTarget(element, nextPlacement) {
      if (target === element && placement === nextPlacement && target?.classList.contains(`drop-${placement}`)) return
      clearPreview()
      target = element
      placement = nextPlacement
      target?.classList.add(`drop-${placement}`)
    },
    showEnd() {
      if (atEnd) return
      clearPreview()
      atEnd = true
      if (getEndMarker()) getEndMarker().hidden = false
    },
    setSource(element) {
      clearSource()
      source = element
      source?.classList.add('dragging')
    },
    clearPreview,
    clear() {
      clearPreview()
      clearSource()
    },
    restore() {
      // Vue can update list rows during a background refresh or selection.
      // Restore transient classes, or discard a target removed by that update.
      if (target) {
        if (getRoot()?.contains(target)) target.classList.add(`drop-${placement}`)
        else clearPreview()
      }
      if (source) {
        if (getRoot()?.contains(source)) source.classList.add('dragging')
        else clearSource()
      }
      if (getEndMarker()) getEndMarker().hidden = !atEnd
    },
  }
}
