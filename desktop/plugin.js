import { host, ROUTES_AREA, SIDEBAR_NAV_AREA, PALETTE_AREA } from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'
import { useState } from 'react'

const KEY = 'project-manager.workspace.v1'
const blank = () => ({ projects: [] })
function load() {
  try { const value = JSON.parse(localStorage.getItem(KEY) || 'null'); return value && Array.isArray(value.projects) ? value : blank() }
  catch { return blank() }
}
function Page() {
  const [data, setData] = useState(load)
  const [selected, setSelected] = useState(null)
  const [name, setName] = useState('')
  const [sectionName, setSectionName] = useState('')
  const [unitName, setUnitName] = useState('')
  const [draft, setDraft] = useState('')
  const [message, setMessage] = useState('Your workspace is stored locally in this Desktop profile.')
  const persist = next => {
    try { localStorage.setItem(KEY, JSON.stringify(next)); setData(next); setMessage('Saved on this device.') }
    catch { setMessage('Could not save locally; your last saved workspace is unchanged.') }
  }
  const project = data.projects.find(p => p.id === selected)
  const [selectedUnitId, setSelectedUnitId] = useState(null)
  const selectedUnit = project?.sections.flatMap(s => s.units).find(u => u.id === selectedUnitId)
  const updateUnit = (unitId, patch) => {
    if (!project) return
    persist({ ...data, projects: data.projects.map(p => p.id !== selected ? p : { ...p, sections: p.sections.map(s => ({ ...s, units: s.units.map(u => u.id === unitId ? { ...u, ...patch } : u) })) }) })
  }
  const openUnit = unit => { setSelectedUnitId(unit.id); setDraft(typeof unit.text === 'string' ? unit.text : '') }
  const makeProject = () => { const title = name.trim(); if (!title) return; const id = globalThis.crypto?.randomUUID?.() || String(Date.now()); const next = { ...data, projects: [...data.projects, { id, name: title, sections: [] }] }; persist(next); setSelected(id); setSelectedUnitId(null); setName('') }
  const addSection = () => { if (!project || !sectionName.trim()) return; persist({ ...data, projects: data.projects.map(p => p.id === selected ? { ...p, sections: [...p.sections, { id: String(Date.now()), name: sectionName.trim(), units: [] }] } : p) }); setSectionName('') }
  const addUnit = sectionId => { if (!project || !unitName.trim()) return; const unit = { id: String(Date.now()), name: unitName.trim(), text: '' }; persist({ ...data, projects: data.projects.map(p => p.id === selected ? { ...p, sections: p.sections.map(s => s.id === sectionId ? { ...s, units: [...s.units, unit] } : s) } : p) }); setUnitName(''); openUnit(unit) }
  const field = (label, value, set, placeholder) => jsx('input', { 'aria-label': label, value, placeholder, onChange: e => set(e.target.value) })
  const editor = selectedUnit && project ? jsxs('section', { 'aria-label': `Unit editor: ${selectedUnit.name}`, children: [jsx('h3', { children: selectedUnit.name }), jsx('label', { htmlFor: 'unit-text', children: 'Unit text' }), jsx('textarea', { id: 'unit-text', 'aria-label': 'Unit text', value: draft, onChange: e => setDraft(e.target.value), rows: 12 }), jsx('button', { type: 'button', onClick: () => updateUnit(selectedUnit.id, { text: draft }), children: 'Save unit' }), jsx('button', { type: 'button', onClick: () => { setSelectedUnitId(null); setDraft('') }, children: 'Close editor' })] }) : null
  return jsxs('main', { style: { maxWidth: 900, margin: '32px auto', padding: 24, fontFamily: 'system-ui', color: 'var(--text-primary, #222)' }, children: [
    jsxs('header', { children: [jsx('h1', { children: 'Project Manager' }), jsx('p', { children: 'A blank-first-run workspace for organizing projects, sections, and units.' })] }),
    jsx('p', { role: 'status', children: message }),
    jsxs('section', { 'aria-label': 'Projects', children: [jsx('h2', { children: 'Projects' }), ...data.projects.map(p => jsx('button', { type: 'button', 'aria-current': selected === p.id ? 'page' : undefined, onClick: () => { setSelected(p.id); setSelectedUnitId(null) }, style: { margin: 4, padding: 10 }, children: p.name }, p.id)), jsx('div', { children: [field('New project name', name, setName, 'Project name'), jsx('button', { type: 'button', onClick: makeProject, children: 'Create project' })] })] }),
    project ? jsxs('section', { 'aria-label': `${project.name} sections`, children: [jsx('h2', { children: project.name }), jsx('div', { children: [field('New section name', sectionName, setSectionName, 'Section name'), jsx('button', { type: 'button', onClick: addSection, children: 'Add section' })] }), ...project.sections.map(section => jsxs('article', { style: { borderTop: '1px solid #bbb', padding: 12 }, children: [jsx('h3', { children: section.name }), ...section.units.map(unit => jsx('button', { type: 'button', onClick: () => openUnit(unit), children: unit.name }, unit.id)), jsx('div', { children: [field(`New unit in ${section.name}`, unitName, setUnitName, 'Unit name'), jsx('button', { type: 'button', onClick: () => addUnit(section.id), children: 'Add unit' })] })] }, section.id)), editor] }) : jsx('p', { children: data.projects.length ? 'Choose a project to view its sections.' : 'No projects yet. Create one to get started.' })
  ] })
}
export default { id: 'project-manager', name: 'Project Manager', description: 'Local-first project, section, and unit editing.', register(ctx) { ctx.registerMany([{ id: 'page', area: ROUTES_AREA, data: { path: '/project-manager' }, render: () => jsx(Page, {}) }, { id: 'nav', area: SIDEBAR_NAV_AREA, data: { path: '/project-manager', label: 'Project Manager', codicon: 'folder' } }, { id: 'open', area: PALETTE_AREA, data: { id: 'project-manager.open', label: 'Open Project Manager', keywords: ['projects', 'sections', 'units'], run: () => host.navigate('/project-manager') } }]) } }
