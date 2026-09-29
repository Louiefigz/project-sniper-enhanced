/** Validate every syntax node of one composition script against the closed confinement subset. */
import { parse } from "acorn";
import { CALLABLE_GLOBALS, DENIED_ATTRIBUTES, DENIED_KEYS, DENIED_MEMBERS, DENIED_PROPERTIES, HTML_TAGS,
  MEMBER_GLOBALS, QUERY_METHODS, SVG_TAGS, Scope, TWEEN_METHODS, VALUE_GLOBALS, astNode, astNodes, collect,
  fail, staticName, textAllowed, type AstNode } from "./native-composition-script-scope";

const SCOPED_GLOBALS = new Set(["document", "window", "gsap", "__hyperframes"]);
const INDIRECT = new Set(["call", "apply", "bind"]);

function literalString(value: AstNode | undefined): string | undefined {
  return value?.type === "Literal" && typeof value.value === "string" ? value.value : undefined;
}

function identifierName(value: AstNode): string | undefined {
  return value.type === "Identifier" ? value.name as string : undefined;
}

class Validator {
  constructor(private scope: Scope, private ownIds: Set<string>) {}

  statement(n: AstNode): void {
    const child = (key: string) => astNode(n[key]);
    switch (n.type) {
      case "ExpressionStatement": return this.expression(child("expression"));
      case "VariableDeclaration":
        for (const row of astNodes(n.declarations)) {
          this.pattern(astNode(row.id));
          if (row.init) this.expression(astNode(row.init), astNode(row.id).type === "Identifier");
        }
        return;
      case "FunctionDeclaration": return this.fn(n);
      case "ReturnStatement": case "ThrowStatement": if (n.argument) this.expression(child("argument")); return;
      case "IfStatement":
        this.expression(child("test")); this.statement(child("consequent"));
        if (n.alternate) this.statement(child("alternate"));
        return;
      case "BlockStatement": astNodes(n.body).forEach(row => this.statement(row)); return;
      case "ForStatement": return this.forLoop(n);
      case "ForOfStatement": case "ForInStatement": return this.forEach(n);
      case "WhileStatement": case "DoWhileStatement": this.expression(child("test")); this.statement(child("body")); return;
      case "BreakStatement": case "ContinueStatement": if (n.label) fail("labelled jump"); return;
      case "EmptyStatement": return;
      case "TryStatement": return this.tryStatement(n);
      case "SwitchStatement":
        this.expression(child("discriminant"));
        for (const row of astNodes(n.cases)) {
          if (row.test) this.expression(astNode(row.test));
          astNodes(row.consequent).forEach(statement => this.statement(statement));
        }
        return;
      default: fail(`statement ${n.type}`);
    }
  }

  forLoop(n: AstNode): void {
    if (n.init) {
      const init = astNode(n.init);
      if (init.type === "VariableDeclaration") this.statement(init); else this.expression(init);
    }
    if (n.test) this.expression(astNode(n.test));
    if (n.update) this.expression(astNode(n.update));
    this.statement(astNode(n.body));
  }

  forEach(n: AstNode): void {
    if (n.await) fail("asynchronous iteration");
    const left = astNode(n.left);
    if (left.type === "VariableDeclaration") astNodes(left.declarations).forEach(row => this.pattern(astNode(row.id)));
    else this.target(left);
    this.expression(astNode(n.right));
    this.statement(astNode(n.body));
  }

  tryStatement(n: AstNode): void {
    this.statement(astNode(n.block));
    if (n.handler) {
      const handler = astNode(n.handler);
      if (handler.param) this.pattern(astNode(handler.param));
      this.statement(astNode(handler.body));
    }
    if (n.finalizer) this.statement(astNode(n.finalizer));
  }

  fn(n: AstNode): void {
    if (n.generator || n.async) fail("generator or asynchronous function");
    astNodes(n.params).forEach(row => this.pattern(row));
    const body = astNode(n.body);
    if (body.type === "BlockStatement") this.statement(body); else this.expression(body);
  }

  pattern(n: AstNode): void {
    if (n.type === "Identifier") return;
    if (n.type === "AssignmentPattern") { this.pattern(astNode(n.left)); this.expression(astNode(n.right)); return; }
    if (n.type === "RestElement") return this.pattern(astNode(n.argument));
    if (n.type === "ArrayPattern") return astNodes(n.elements).forEach(row => this.pattern(row));
    if (n.type !== "ObjectPattern") fail(`binding ${n.type}`);
    for (const property of astNodes(n.properties)) {
      if (property.type === "RestElement") { this.pattern(astNode(property.argument)); continue; }
      const key = astNode(property.key), name = identifierName(key) ?? literalString(key);
      if (property.computed || !name || DENIED_MEMBERS.has(name)) fail("destructured member is dynamic or denied");
      this.pattern(astNode(property.value));
    }
  }

  expression(n: AstNode, hostInitializer = false): void {
    switch (n.type) {
      case "Identifier": return this.identifier(n);
      case "Literal": textAllowed(n.value); textAllowed((n.regex as { pattern?: string } | undefined)?.pattern); return;
      case "TemplateLiteral":
        astNodes(n.quasis).forEach(row => textAllowed((row.value as { cooked?: string }).cooked));
        return astNodes(n.expressions).forEach(row => this.expression(row));
      case "ArrayExpression": return astNodes(n.elements).forEach(row => this.spreadable(row));
      case "ObjectExpression": return this.object(n);
      case "FunctionExpression": case "ArrowFunctionExpression": return this.fn(n);
      case "UnaryExpression": if (n.operator === "delete") fail("delete"); return this.expression(astNode(n.argument));
      case "UpdateExpression": return this.target(astNode(n.argument));
      case "BinaryExpression": case "LogicalExpression":
        this.expression(astNode(n.left)); return this.expression(astNode(n.right));
      case "AssignmentExpression": this.target(astNode(n.left)); return this.expression(astNode(n.right));
      case "ConditionalExpression":
        ["test", "consequent", "alternate"].forEach(key => this.expression(astNode(n[key]))); return;
      case "SequenceExpression": return astNodes(n.expressions).forEach(row => this.expression(row));
      case "CallExpression": return this.call(n, hostInitializer);
      case "MemberExpression": return this.member(n);
      case "ChainExpression": return this.expression(astNode(n.expression));
      default: fail(`expression ${n.type}`);
    }
  }

  spreadable(n: AstNode): void {
    this.expression(n.type === "SpreadElement" ? astNode(n.argument) : n);
  }

  object(n: AstNode): void {
    for (const property of astNodes(n.properties)) {
      if (property.type === "SpreadElement") { this.expression(astNode(property.argument)); continue; }
      const key = astNode(property.key), name = identifierName(key) ?? literalString(key);
      if (property.kind !== "init" || property.computed || !name || DENIED_KEYS.has(name) || name === "style") {
        fail("object literal uses an accessor, computed or denied key");
      }
      textAllowed(name);
      this.expression(astNode(property.value));
    }
  }

  identifier(n: AstNode): void {
    const name = n.name as string;
    if (VALUE_GLOBALS.has(name)) return;
    if (!this.scope.origins.has(name)) fail(`global ${name} is used as a value`);
    if (this.scope.kinds.get(name) === "root") fail(`host reference ${name} escapes its query role`);
  }

  member(n: AstNode): void {
    const object = astNode(n.object), name = staticName(n), global = identifierName(object);
    if (name !== undefined && DENIED_MEMBERS.has(name)) fail(`member ${name}`);
    if (global && (SCOPED_GLOBALS.has(global) || MEMBER_GLOBALS[global] || CALLABLE_GLOBALS.has(global))) {
      if (name && MEMBER_GLOBALS[global]?.has(name)) return;
      fail(`global member ${global}.${name ?? "[computed]"}`);
    }
    if (name === undefined) {
      if (!global || this.scope.kinds.get(global) !== "data") fail("dynamic member access outside local data");
      return this.expression(astNode(n.property));
    }
    this.receiver(object, name);
  }

  receiver(object: AstNode, name: string): void {
    const id = identifierName(object);
    if (id && this.scope.origins.has(id)) {
      const kind = this.scope.kinds.get(id);
      if (kind === "root" && !QUERY_METHODS.has(name)) fail(`host reference used for ${name}`);
      if (kind === "dynamic") fail("member of a dynamically selected value");
      return;
    }
    if (object.type === "CallExpression" && this.scope.kindOf(object) === "root") {
      if (!QUERY_METHODS.has(name)) fail(`host reference used for ${name}`);
      return this.call(object, true);
    }
    this.expression(object);
  }

  call(n: AstNode, hostAllowed = false): void {
    const callee = astNode(n.callee), args = astNodes(n.arguments);
    if (this.scope.kindOf(n) === "root" && !hostAllowed) fail("host lookup escapes its declaration");
    this.callee(callee, args);
    args.forEach(row => this.spreadable(row));
  }

  callee(callee: AstNode, args: AstNode[]): void {
    const id = identifierName(callee);
    if (id) {
      if (CALLABLE_GLOBALS.has(id) || this.scope.kinds.get(id) === "function") return;
      fail(`call to ${id}`);
    }
    if (["FunctionExpression", "ArrowFunctionExpression"].includes(callee.type)) return this.fn(callee);
    if (callee.type !== "MemberExpression") fail(`callee ${callee.type}`);
    const name = staticName(callee), object = astNode(callee.object);
    if (name === undefined || DENIED_MEMBERS.has(name)) fail(`method ${name ?? "[computed]"}`);
    const global = identifierName(object);
    if (global && !this.scope.origins.has(global)) return this.globalCall(global, name, args);
    if (object.type === "MemberExpression" && identifierName(astNode(object.object)) === "window") {
      if (staticName(object) === "__hyperframes" && name === "getVariables") return;
      fail("window member call");
    }
    if (object.type === "MemberExpression" && staticName(object) === undefined) fail("method of a dynamically selected value");
    if (INDIRECT.has(name)) return this.indirect(object);
    if (TWEEN_METHODS.has(name)) this.tweenVars(name, args);
    const attribute = literalString(args[0]);
    if (name === "setAttribute" && (attribute === undefined || DENIED_ATTRIBUTES.test(attribute))) fail("attribute write");
    if (name === "setProperty" && (attribute === undefined || DENIED_PROPERTIES.test(attribute))) fail("style property write");
    this.receiver(object, name);
  }

  tweenVars(name: string, args: AstNode[]): void {
    if (!this.elementTarget(args[0])) fail(`tween ${name} target is not a proven descendant`);
    const configs = name.includes("FromTo") || name === "fromTo" ? [1, 2] : [1];
    if (name.startsWith("stagger")) configs.forEach((value, index) => { configs[index] = value + 1; });
    for (const index of configs) {
      const config = args[index];
      if (config?.type !== "ObjectExpression") fail("tween properties are not a literal object");
      astNodes(config.properties).forEach(property => this.tweenProperty(property));
    }
  }

  tweenProperty(property: AstNode): void {
    if (property.type !== "Property" || property.computed) fail("tween properties contain an unknown spread or key");
    const key = astNode(property.key), field = identifierName(key) ?? literalString(key);
    if (!field || ["css", "attr", "className", "clearProps", "autoAlpha", "startAt", "keyframes"].includes(field)) {
      fail("tween properties can alter hidden hosts or contain another property bag");
    }
  }

  indirect(object: AstNode): void {
    const inner = object.type === "MemberExpression" ? staticName(object) : undefined;
    const holder = inner ? astNode(object.object) : undefined;
    if (!inner || DENIED_MEMBERS.has(inner) || INDIRECT.has(inner) || TWEEN_METHODS.has(inner)
        || (holder?.type === "MemberExpression" && staticName(holder) === undefined)) fail("indirect call");
    this.receiver(astNode(object.object), inner);
  }

  globalCall(global: string, name: string, args: AstNode[]): void {
    // Only the composition's own literal root id: the scoped proxy then resolves the host itself, and an
    // unscoped fallback (no host found) can never reach another element through a computed or foreign id.
    if (global === "document" && name === "getElementById" && this.ownIds.has(literalString(args[0]) ?? "")) return;
    if (global === "document" && name === "createElement" && HTML_TAGS.has(literalString(args[0]) ?? "")) return;
    if (global === "document" && name === "createElementNS" && SVG_TAGS.has(literalString(args[1]) ?? "")) return;
    if (global === "document" && name === "createTextNode") return;
    if (global === "gsap" && name === "timeline") return;
    if (global === "__hyperframes" && name === "getVariables") return;
    if (MEMBER_GLOBALS[global]?.has(name)) return;
    fail(`global call ${global}.${name}`);
  }

  elementTarget(value: AstNode | undefined): boolean {
    if (!value) return false;
    if (value.type === "Identifier") return this.scope.kinds.get(value.name as string) === "element";
    if (value.type === "ArrayExpression") return astNodes(value.elements).every(row => this.elementTarget(row));
    return value.type === "CallExpression" && this.scope.kindOf(value) === "element";
  }

  target(n: AstNode): void {
    const id = identifierName(n);
    if (id) {
      if (!this.scope.origins.has(id)) fail(`assignment to global ${id}`);
      return;
    }
    if (n.type !== "MemberExpression") fail(`assignment target ${n.type}`);
    if (this.timelineRegistration(n)) return;
    const name = staticName(n), object = astNode(n.object), global = identifierName(object);
    if (name === undefined || DENIED_MEMBERS.has(name)) fail("dynamic or denied member assignment");
    if (global && !this.scope.origins.has(global)) fail(`assignment to ${global}.${name}`);
    if (identifierName(object) && this.scope.kinds.get(identifierName(object)!) === "root") fail("host mutation");
    if (object.type === "MemberExpression" && staticName(object) === undefined) fail("assignment into a dynamically selected value");
    this.receiver(object, name);
  }

  timelineRegistration(n: AstNode): boolean {
    const registry = astNode(n.object), key = literalString(astNode(n.property));
    return Boolean(n.computed && key && this.ownIds.has(key) && registry.type === "MemberExpression"
      && identifierName(astNode(registry.object)) === "window" && staticName(registry) === "__timelines");
  }
}

/** Parse and prove one inline script; ownIds are the host and authored composition identities. */
export function assertConfinedCompositionScript(source: string, ownIds: string[]): void {
  let program: AstNode;
  try {
    program = astNode(parse(source, { ecmaVersion: 2022, sourceType: "script" }));
  } catch {
    fail("inline script does not parse");
  }
  const scope = new Scope();
  collect(scope, program);
  scope.resolve();
  const validator = new Validator(scope, new Set(ownIds));
  astNodes(program.body).forEach(row => validator.statement(row));
}
