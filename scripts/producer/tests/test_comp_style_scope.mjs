/** Installed-parser contract: page CSS cannot leak across mounted catalog cards. */
import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import { scopeScript } from '../studio/comp_style_scope.mjs';

test('scopes only syntax nodes, preserving strings, regexes and comments', () => {
  const unchanged = `// document.documentElement.style\nconst label='document.body.style';
const pattern=/document.documentElement.style/;`;
  assert.equal(scopeScript(unchanged, 'card-root'), unchanged);
  const raw = `document . documentElement . style.setProperty('--accent', color);`;
  assert.equal(scopeScript(raw, 'card-root'), `document.getElementById("card-root").style.setProperty('--accent', color);`);
});

test('two mounted cards retain independent selected accents and untouched page', () => {
  const values = new Map(), makeStyle = key => ({setProperty:(name,value)=>values.set(key+name,value)});
  const roots = new Map([['first-root',{style:makeStyle('first')}],['second-root',{style:makeStyle('second')}]]);
  const document = {documentElement:{style:makeStyle('page')},body:{style:makeStyle('body')},getElementById:key=>roots.get(key)};
  const raw = `document.documentElement.style.setProperty('--accent', color);`;
  vm.runInNewContext(scopeScript(raw,'first-root'), {document,color:'#054BC9'});
  vm.runInNewContext(scopeScript(raw,'second-root'), {document,color:'#7FB4FF'});
  assert.deepEqual([...values], [['first--accent','#054BC9'],['second--accent','#7FB4FF']]);
});

test('same root works standalone and page background writes remain local', () => {
  const root={style:{}},page={style:{}},body={style:{}};
  const document={getElementById:()=>root,documentElement:page,body};
  const source=`document.documentElement.style.background='transparent';document.body.style.opacity='1';`;
  vm.runInNewContext(scopeScript(source,'standalone-root'),{document});
  assert.deepEqual(root.style,{background:'transparent',opacity:'1'});
  assert.deepEqual(page.style,{});assert.deepEqual(body.style,{});
});

test('missing parser syntax, invalid scope and shadowed document fail closed', () => {
  assert.throws(()=>scopeScript('document.body.style = {','root'));
  assert.throws(()=>scopeScript('document.body.style.opacity = 1;','bad root'));
  assert.throws(()=>scopeScript('function f(document) {document.body.style.opacity=1;}','root'),/shadows/);
  assert.throws(()=>scopeScript('const document = {}; document.body.style.opacity=1;','root'),/shadows/);
});

test('already scoped catalog statements are idempotent', () => {
  const source=`document.documentElement.style.setProperty('--accent', vars.accentColor);`;
  const result=scopeScript(source,'st-root');
  assert.equal(scopeScript(result,'st-root'),result);
});
