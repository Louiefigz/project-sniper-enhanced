/** Root animation may write known root nodes, but cannot read a composition's mutable content. */
import { parse } from "acorn";
import { astNode, fail, type AstNode } from "./native-composition-script-scope";

function identifier(value: unknown, name: string): boolean {
  const node = astNode(value);
  return node.type === "Identifier" && node.name === name;
}

function member(value: unknown, owner: string, name: string): boolean {
  const node = astNode(value);
  return node.type === "MemberExpression" && !node.computed && identifier(node.object, owner)
    && identifier(node.property, name);
}

function literal(value: unknown): void {
  const node = astNode(value);
  if (node.type === "Literal" && !node.regex) {
    if (typeof node.value === "string" && /visibility|autoAlpha|counter-|url\(|var\(/iu.test(node.value)) {
      fail("root tween reads a shared resource or controls hidden hosts");
    }
    return;
  }
  if (node.type === "UnaryExpression" && ["+", "-"].includes(String(node.operator))) return literal(node.argument);
  if (node.type === "ArrayExpression") return (node.elements as unknown[]).forEach(literal);
  if (node.type !== "ObjectExpression") fail("root tween value reads mutable state");
  for (const value of node.properties as unknown[]) {
    const property = astNode(value);
    if (property.type === "SpreadElement") { literal(property.argument); continue; }
    if (property.type !== "Property" || property.computed || property.kind !== "init" || property.method) {
      fail("root tween property is not a constant");
    }
    const key = astNode(property.key), name = key.type === "Identifier" ? key.name : key.value;
    if (typeof name !== "string" || /visibility|autoAlpha|counter|clearProps|className|attr|on[A-Z]|__proto__/u.test(name)) {
      fail("root tween can change global dependencies");
    }
    literal(property.value);
  }
}

function registration(node: AstNode): boolean {
  if (node.type !== "AssignmentExpression" || node.operator !== "=") return false;
  const left = astNode(node.left), right = astNode(node.right);
  if (member(left, "window", "__timelines")) {
    return right.type === "LogicalExpression" && right.operator === "||"
      && member(right.left, "window", "__timelines") && astNode(right.right).type === "ObjectExpression"
      && (astNode(right.right).properties as unknown[]).length === 0;
  }
  const key = left.type === "MemberExpression" ? astNode(left.property) : undefined;
  return left.type === "MemberExpression" && Boolean(left.computed) && member(left.object, "window", "__timelines")
    && key?.type === "Literal" && key.value === "native-canvas" && identifier(right, "tl");
}

function tween(node: AstNode, rootIds: Set<string>): void {
  if (node.type !== "CallExpression") fail("root animation contains non-tween work");
  const callee = astNode(node.callee), property = callee.type === "MemberExpression" ? astNode(callee.property) : undefined;
  if (callee.type !== "MemberExpression" || callee.computed || !identifier(callee.object, "tl")
      || property?.type !== "Identifier" || !["to", "from", "fromTo", "set"].includes(String(property.name))) {
    fail("root animation can inspect composition contents");
  }
  const args = node.arguments as unknown[], target = astNode(args[0]);
  const empty = target.type === "ObjectExpression" && (target.properties as unknown[]).length === 0;
  if (!empty && !(target.type === "Literal" && typeof target.value === "string"
      && /^#[A-Za-z][A-Za-z0-9_-]*$/u.test(target.value) && rootIds.has(target.value.slice(1)))) {
    fail("root tween target is not an exact existing root id");
  }
  args.slice(1).forEach(literal);
}

function statement(value: unknown, rootIds: Set<string>): void {
  const node = astNode(value);
  if (node.type === "VariableDeclaration") {
    const declarations = node.declarations as unknown[], declaration = astNode(declarations[0]);
    const init = astNode(declaration.init);
    if (declarations.length !== 1 || node.kind !== "const" || !identifier(declaration.id, "tl")
        || init.type !== "CallExpression" || !member(init.callee, "gsap", "timeline")) {
      fail("root declaration reads mutable composition state");
    }
    (init.arguments as unknown[]).forEach(literal);
    return;
  }
  if (node.type !== "ExpressionStatement") fail("root script is not a constant timeline");
  const expression = astNode(node.expression);
  if (!registration(expression)) tween(expression, rootIds);
}

/** Accept generated constant timeline statements; custom root logic requires full invalidation. */
export function rootScriptsIsolated(scripts: string[], rootIds: Set<string>): boolean {
  try {
    for (const source of scripts) {
      const program = astNode(parse(source, { ecmaVersion: 2022, sourceType: "script" }));
      (program.body as unknown[]).forEach(value => statement(value, rootIds));
    }
    return true;
  } catch {
    return false;
  }
}
