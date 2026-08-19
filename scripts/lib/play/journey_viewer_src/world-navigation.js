import * as THREE from 'three'

export function createWorldNavigation({canvas, camera, frozenRef, interactionMeshes, semanticMeshes, onSelect}) {
  const raycaster = new THREE.Raycaster()
  const pointer = new THREE.Vector2()
  const actionableMeshes = interactionMeshes.concat(semanticMeshes)
  const walkOffset = new THREE.Vector3()
  const currentLookDirection = new THREE.Vector3(0, 0, -1)
  let lookYaw = 0
  let lookPitch = 0
  let pointerDown = false
  let pointerMoved = false
  let pointerX = 0
  let pointerY = 0

  const pointRaycaster = (event) => {
    const bounds = canvas.getBoundingClientRect()
    pointer.x = ((event.clientX - bounds.left) / bounds.width) * 2 - 1
    pointer.y = -((event.clientY - bounds.top) / bounds.height) * 2 + 1
    raycaster.setFromCamera(pointer, camera)
  }

  const onPointerDown = (event) => {
    if (!frozenRef.current || event.button !== 0) return
    pointerDown = true
    pointerMoved = false
    pointerX = event.clientX
    pointerY = event.clientY
    canvas.classList.add('looking')
    canvas.setPointerCapture?.(event.pointerId)
  }

  const onPointerMove = (event) => {
    if (!pointerDown) {
      pointRaycaster(event)
      const actionable = raycaster.intersectObjects(actionableMeshes, false)[0]
      canvas.classList.toggle('vantage-hover', Boolean(actionable))
      return
    }
    if (!frozenRef.current) return
    const deltaX = event.clientX - pointerX
    const deltaY = event.clientY - pointerY
    if (Math.abs(deltaX) + Math.abs(deltaY) > 2) pointerMoved = true
    lookYaw -= deltaX * .006
    lookPitch = THREE.MathUtils.clamp(lookPitch - deltaY * .0045, -.82, .82)
    pointerX = event.clientX
    pointerY = event.clientY
  }

  const onPointerUp = (event) => {
    pointerDown = false
    canvas.classList.remove('looking')
    canvas.releasePointerCapture?.(event.pointerId)
  }

  const onWheel = (event) => {
    if (!frozenRef.current) return
    event.preventDefault()
    const stride = THREE.MathUtils.clamp(-event.deltaY * .008, -1.8, 1.8)
    const groundDirection = currentLookDirection.clone().setY(0)
    if (groundDirection.lengthSq() < .001) return
    groundDirection.normalize()
    walkOffset.addScaledVector(groundDirection, stride)
    if (walkOffset.length() > 12) walkOffset.setLength(12)
  }

  const onClick = (event) => {
    if (pointerMoved) {
      pointerMoved = false
      return
    }
    pointRaycaster(event)
    const interactionHit = raycaster.intersectObjects(interactionMeshes, false)[0]
    if (interactionHit) {
      onSelect(interactionHit.object.userData)
      return
    }
    const semanticHit = raycaster.intersectObjects(semanticMeshes, false)[0]
    if (semanticHit) {
      onSelect(semanticHit.object.userData)
      return
    }
    if (frozenRef.current) onSelect(null)
  }

  const onKeyDown = (event) => {
    if (!frozenRef.current || event.target instanceof HTMLInputElement || event.target instanceof HTMLButtonElement) return
    const key = event.key.toLowerCase()
    const horizontal = event.key === 'ArrowLeft' || key === 'a' ? .16 : event.key === 'ArrowRight' || key === 'd' ? -.16 : 0
    const vertical = event.key === 'ArrowUp' || key === 'w' ? .1 : event.key === 'ArrowDown' || key === 's' ? -.1 : 0
    if (!horizontal && !vertical) return
    event.preventDefault()
    lookYaw += horizontal
    lookPitch = THREE.MathUtils.clamp(lookPitch + vertical, -.82, .82)
  }

  canvas.addEventListener('pointerdown', onPointerDown)
  canvas.addEventListener('pointermove', onPointerMove)
  canvas.addEventListener('pointerup', onPointerUp)
  canvas.addEventListener('pointercancel', onPointerUp)
  canvas.addEventListener('wheel', onWheel, {passive: false})
  canvas.addEventListener('click', onClick)
  window.addEventListener('keydown', onKeyDown)

  return {
    applyFrozenView(current, direction, desiredCamera, desiredLook) {
      const baseYaw = Math.atan2(direction.x, -direction.z)
      const yaw = baseYaw + lookYaw
      const lookDirection = new THREE.Vector3(
        Math.sin(yaw) * Math.cos(lookPitch),
        Math.sin(lookPitch),
        -Math.cos(yaw) * Math.cos(lookPitch),
      )
      currentLookDirection.copy(lookDirection)
      desiredCamera.copy(current).addScaledVector(direction, -1.4).add(walkOffset)
      desiredCamera.y = 2.25
      desiredLook.copy(desiredCamera).addScaledVector(lookDirection, 12)
    },
    reset() {
      lookYaw = 0
      lookPitch = 0
      walkOffset.set(0, 0, 0)
    },
    dispose() {
      window.removeEventListener('keydown', onKeyDown)
      canvas.removeEventListener('pointerdown', onPointerDown)
      canvas.removeEventListener('pointermove', onPointerMove)
      canvas.removeEventListener('pointerup', onPointerUp)
      canvas.removeEventListener('pointercancel', onPointerUp)
      canvas.removeEventListener('wheel', onWheel)
      canvas.removeEventListener('click', onClick)
    },
  }
}
