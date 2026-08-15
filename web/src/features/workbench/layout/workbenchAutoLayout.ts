import type { NodeSize, Point, WorkbenchEdge, WorkbenchNode } from '../types/workbenchTypes';

export const WORKBENCH_OVERVIEW_VIEWPORT = { x: 40, y: 40, zoom: 0.4 } as const;

export type WorkbenchLayoutFamily = 'asset' | 'operation' | 'result' | 'shot' | string;

export interface WorkbenchLayoutRelationshipRule {
  sourceFamily: WorkbenchLayoutFamily;
  targetFamily: WorkbenchLayoutFamily;
  affinity: number;
}

export interface WorkbenchAutoLayoutOptions {
  sizes?: Record<string, NodeSize>;
  origin?: Point;
  columnGap?: number;
  rowGap?: number;
  maxColumnHeight?: number;
  fixedNodeKeys?: ReadonlySet<string>;
  relationshipRules?: WorkbenchLayoutRelationshipRule[];
}

function sectionMemberKeys(node: WorkbenchNode) {
  return Array.isArray(node.data.node_keys)
    ? node.data.node_keys.filter((key): key is string => typeof key === 'string')
    : [];
}

/** Higher affinity means the target column should follow its source sooner. */
export const WORKBENCH_LAYOUT_RELATIONSHIP_RULES: WorkbenchLayoutRelationshipRule[] = [
  { sourceFamily: 'asset', targetFamily: 'shot', affinity: 220 },
  { sourceFamily: 'shot', targetFamily: 'result', affinity: 360 },
];

const EDGE_AFFINITY: Record<string, number> = {
  operation_input: 140,
  candidate_output: 130,
  output_binding: 120,
  shot_sequence: 100,
  asset_reference: 60,
  unsupported: 1,
};
const DEFAULT_NODE_SIZE: NodeSize = { width: 360, height: 280 };
const DEFAULT_ORIGIN: Point = { x: 80, y: 80 };
const DEFAULT_COLUMN_GAP = 180;
const DEFAULT_ROW_GAP = 72;
const BARYCENTRIC_SWEEPS = 4;
const HEADER_BAND_ORDER: Record<string, number> = {};
const ASSET_PRELUDE_ORDER: Record<string, number> = {
  character: 0,
  object: 1,
  scene: 2,
};

function stringData(node: WorkbenchNode, ...keys: string[]) {
  for (const key of keys) {
    const value = node.data[key];
    if (typeof value === 'string' && value)
      return value;
  }
  return '';
}

export function workbenchLayoutFamily(node: WorkbenchNode): WorkbenchLayoutFamily {
  const configured = stringData(node, 'layout_family');
  if (configured)
    return configured;
  if (node.kind === 'asset')
    return 'asset';
  if (node.kind === 'video_result')
    return 'result';
  if (node.kind === 'shot')
    return 'shot';
  return node.kind;
}

export function workbenchLayoutLane(node: WorkbenchNode) {
  const configured = stringData(node, 'layout_lane');
  if (configured)
    return configured;
  const family = workbenchLayoutFamily(node);
  if (family === 'asset')
    return `asset:${stringData(node, 'asset_type', 'assetType') || 'generic'}`;
  if (family === 'operation')
    return `operation:${stringData(node, 'capability_key', 'capabilityKey') || node.backendKind || node.kind}`;
  if (family === 'result') {
    if (stringData(node, 'watermark_node_key'))
      return 'result:watermarked-video';
    return `result:${node.backendKind || node.kind}`;
  }
  return family;
}

export function workbenchLayoutBand(node: WorkbenchNode) {
  const configured = stringData(node, 'layout_band');
  if (configured)
    return configured;
  return 'main';
}

/**
 * Treat background sections as atomic layout units. Members retain their
 * relative positions so arranging the canvas never tears a section apart.
 */
export function buildWorkbenchGroupedAutoLayout(
  nodes: WorkbenchNode[],
  edges: WorkbenchEdge[] = [],
  options: WorkbenchAutoLayoutOptions = {},
) {
  const nodeByKey = new Map(nodes.map(node => [node.key, node]));
  const sections = nodes.filter(node => node.kind === 'section');
  const groupedMemberKeys = new Set(sections.flatMap(sectionMemberKeys));
  const layoutUnits = nodes.filter(node =>
    node.kind === 'section'
    || (!['chapter', 'note'].includes(node.kind) && !groupedMemberKeys.has(node.key)),
  );
  const unitLayout = buildWorkbenchAutoLayout(layoutUnits, edges, options);
  const result: Record<string, Point> = {};
  for (const [nodeKey, position] of Object.entries(unitLayout)) {
    const node = nodeByKey.get(nodeKey);
    if (!node)
      continue;
    result[nodeKey] = position;
    if (node.kind !== 'section')
      continue;
    const offset = {
      x: position.x - node.position.x,
      y: position.y - node.position.y,
    };
    for (const memberKey of sectionMemberKeys(node)) {
      const member = nodeByKey.get(memberKey);
      if (member) {
        result[memberKey] = {
          x: member.position.x + offset.x,
          y: member.position.y + offset.y,
        };
      }
    }
  }
  for (const key of options.fixedNodeKeys ?? []) {
    const node = nodeByKey.get(key);
    if (node)
      result[key] = { ...node.position };
  }
  return result;
}

function orderedHeaderBandNames(names: string[]) {
  return [...names].sort((left, right) => (
    (HEADER_BAND_ORDER[left] ?? Number.MAX_SAFE_INTEGER)
    - (HEADER_BAND_ORDER[right] ?? Number.MAX_SAFE_INTEGER)
    || left.localeCompare(right, undefined, { numeric: true })
  ));
}

function stableNodes(nodes: WorkbenchNode[]) {
  return [...nodes].sort((left, right) => (
    left.position.y - right.position.y
    || left.position.x - right.position.x
    || left.key.localeCompare(right.key, undefined, { numeric: true })
  ));
}

function shotSequence(node: WorkbenchNode) {
  if (workbenchLayoutFamily(node) !== 'shot')
    return null;
  for (const key of ['shot_index', 'shotIndex']) {
    const value = node.data[key];
    if (typeof value === 'number' && Number.isFinite(value))
      return value;
    if (typeof value === 'string' && value.trim() && Number.isFinite(Number(value)))
      return Number(value);
  }
  for (const value of [node.title, node.key]) {
    const match = value.match(/(?:镜头|shot)[-_\s]*(\d+)/i);
    if (match)
      return Number(match[1]);
  }
  return null;
}

function enforcePinnedSequenceOrder(
  columns: WorkbenchNode[][],
  nodeByKey: Map<string, WorkbenchNode>,
  incoming: Map<string, Set<string>>,
  outgoing: Map<string, Set<string>>,
) {
  const connectedShotSequence = (node: WorkbenchNode) => {
    if (workbenchLayoutFamily(node) !== 'result')
      return null;
    const neighbors = new Set([
      ...(incoming.get(node.key) ?? []),
      ...(outgoing.get(node.key) ?? []),
    ]);
    const sequences = [...neighbors].flatMap((key) => {
      const neighbor = nodeByKey.get(key);
      const sequence = neighbor ? shotSequence(neighbor) : null;
      return sequence === null ? [] : [sequence];
    });
    return sequences.length
      ? sequences.reduce((sum, sequence) => sum + sequence, 0) / sequences.length
      : null;
  };
  for (const column of columns) {
    if (!column.length)
      continue;
    const previous = new Map(column.map((node, index) => [node.key, index]));
    const isShotColumn = column.every(node => workbenchLayoutFamily(node) === 'shot');
    column.sort((left, right) => {
      if (isShotColumn) {
        const leftSequence = shotSequence(left);
        const rightSequence = shotSequence(right);
        if (leftSequence !== null && rightSequence !== null && leftSequence !== rightSequence)
          return leftSequence - rightSequence;
        if (leftSequence !== null && rightSequence === null)
          return -1;
        if (leftSequence === null && rightSequence !== null)
          return 1;
      }
      else {
        const leftShotSequence = connectedShotSequence(left);
        const rightShotSequence = connectedShotSequence(right);
        if (
          leftShotSequence !== null
          && rightShotSequence !== null
          && leftShotSequence !== rightShotSequence
        ) {
          return leftShotSequence - rightShotSequence;
        }
        if (leftShotSequence !== null && rightShotSequence === null)
          return -1;
        if (leftShotSequence === null && rightShotSequence !== null)
          return 1;
      }
      return previous.get(left.key)! - previous.get(right.key)!;
    });
  }
}

function nodeSize(node: WorkbenchNode, measured: Record<string, NodeSize>) {
  const candidate = measured[node.key] ?? node.size ?? DEFAULT_NODE_SIZE;
  return {
    width: candidate.width > 0 ? candidate.width : DEFAULT_NODE_SIZE.width,
    height: candidate.height > 0 ? candidate.height : DEFAULT_NODE_SIZE.height,
  };
}

function packLane(
  nodes: WorkbenchNode[],
  sizes: Record<string, NodeSize>,
  rowGap: number,
  maxColumnHeight: number,
) {
  const columns: WorkbenchNode[][] = [];
  let height = 0;
  for (const node of nodes) {
    const nextHeight = height + (height ? rowGap : 0) + sizes[node.key]!.height;
    if (height && nextHeight > maxColumnHeight) {
      columns.push([]);
      height = 0;
    }
    if (!columns.length)
      columns.push([]);
    columns.at(-1)!.push(node);
    height += (height ? rowGap : 0) + sizes[node.key]!.height;
  }
  return columns;
}

function preserveFixedPositions(
  nodes: WorkbenchNode[],
  positions: Record<string, Point>,
  fixedNodeKeys: ReadonlySet<string> | undefined,
) {
  if (!fixedNodeKeys?.size)
    return;
  const nodeByKey = new Map(nodes.map(node => [node.key, node]));
  for (const key of fixedNodeKeys) {
    const node = nodeByKey.get(key);
    if (node)
      positions[key] = { ...node.position };
  }
}

function graphConnections(nodes: WorkbenchNode[], edges: WorkbenchEdge[]) {
  const keys = new Set(nodes.map(node => node.key));
  const outgoing = new Map(nodes.map(node => [node.key, new Set<string>()]));
  const incoming = new Map(nodes.map(node => [node.key, new Set<string>()]));
  for (const edge of edges) {
    if (!keys.has(edge.source) || !keys.has(edge.target) || edge.source === edge.target)
      continue;
    outgoing.get(edge.source)!.add(edge.target);
    incoming.get(edge.target)!.add(edge.source);
  }
  return { outgoing, incoming };
}

function graphConnectionCounts(nodes: WorkbenchNode[], edges: WorkbenchEdge[]) {
  const counts = new Map(nodes.map(node => [node.key, 0]));
  for (const edge of edges) {
    if (!counts.has(edge.source) || !counts.has(edge.target) || edge.source === edge.target)
      continue;
    counts.set(edge.source, counts.get(edge.source)! + 1);
    counts.set(edge.target, counts.get(edge.target)! + 1);
  }
  return counts;
}

function relationAffinity(
  edge: WorkbenchEdge,
  source: WorkbenchNode,
  target: WorkbenchNode,
  rules: WorkbenchLayoutRelationshipRule[],
) {
  const sourceFamily = workbenchLayoutFamily(source);
  const targetFamily = workbenchLayoutFamily(target);
  const relationship = rules.find(rule => rule.sourceFamily === sourceFamily && rule.targetFamily === targetFamily);
  return relationship?.affinity ?? EDGE_AFFINITY[edge.type] ?? 40;
}

function lanePreludeOrder(nodes: WorkbenchNode[]) {
  if (nodes.some(node => stringData(node, 'layout_column_position') === 'first'))
    return -1;
  const orders = nodes.flatMap((node) => {
    if (node.kind !== 'asset')
      return [];
    const assetType = stringData(node, 'asset_type', 'assetType');
    return assetType in ASSET_PRELUDE_ORDER ? [ASSET_PRELUDE_ORDER[assetType]!] : [];
  });
  return orders.length ? Math.min(...orders) : null;
}

function orderedLanes(
  nodes: WorkbenchNode[],
  edges: WorkbenchEdge[],
  rules: WorkbenchLayoutRelationshipRule[],
) {
  const nodeByKey = new Map(nodes.map(node => [node.key, node]));
  const laneNodes = new Map<string, WorkbenchNode[]>();
  for (const node of stableNodes(nodes)) {
    const lane = workbenchLayoutLane(node);
    laneNodes.set(lane, [...(laneNodes.get(lane) ?? []), node]);
  }
  const lanes = [...laneNodes.keys()];
  const outgoing = new Map(lanes.map(lane => [lane, new Map<string, number>()]));
  const incoming = new Map(lanes.map(lane => [lane, new Set<string>()]));
  for (const edge of edges) {
    const source = nodeByKey.get(edge.source);
    const target = nodeByKey.get(edge.target);
    if (!source || !target)
      continue;
    const sourceLane = workbenchLayoutLane(source);
    const targetLane = workbenchLayoutLane(target);
    if (sourceLane === targetLane)
      continue;
    const affinity = relationAffinity(edge, source, target, rules);
    outgoing.get(sourceLane)!.set(targetLane, Math.max(outgoing.get(sourceLane)!.get(targetLane) ?? 0, affinity));
    incoming.get(targetLane)!.add(sourceLane);
  }

  const averageX = new Map(lanes.map((lane) => {
    const members = laneNodes.get(lane)!;
    return [lane, members.reduce((sum, node) => sum + node.position.x, 0) / members.length];
  }));
  const remaining = new Set(lanes);
  const unresolvedIncoming = new Map(lanes.map(lane => [lane, new Set(incoming.get(lane))]));
  const result: string[] = [];

  // Order reusable visual assets by stable category lanes before topology
  // affinity is applied. Chapter and note nodes are excluded by grouped layout.
  const preludeLanes = lanes
    .flatMap((lane) => {
      const order = lanePreludeOrder(laneNodes.get(lane)!);
      return order === null ? [] : [{ lane, order }];
    })
    .sort((left, right) => left.order - right.order || left.lane.localeCompare(right.lane, undefined, { numeric: true }))
    .map(item => item.lane);
  for (const lane of preludeLanes) {
    result.push(lane);
    remaining.delete(lane);
    for (const target of outgoing.get(lane)!.keys())
      unresolvedIncoming.get(target)!.delete(lane);
  }

  while (remaining.size) {
    let candidates = [...remaining].filter(lane => unresolvedIncoming.get(lane)!.size === 0);
    // A malformed or cyclic lane graph must still produce one distinct column
    // per lane. Break the least-constrained cycle deterministically.
    if (!candidates.length) {
      const minimumIncoming = Math.min(...[...remaining].map(lane => unresolvedIncoming.get(lane)!.size));
      candidates = [...remaining].filter(lane => unresolvedIncoming.get(lane)!.size === minimumIncoming);
    }
    const previousLane = result.at(-1);
    candidates.sort((left, right) => {
      const leftAffinity = previousLane ? outgoing.get(previousLane)!.get(left) ?? 0 : 0;
      const rightAffinity = previousLane ? outgoing.get(previousLane)!.get(right) ?? 0 : 0;
      return rightAffinity - leftAffinity
        || averageX.get(left)! - averageX.get(right)!
        || left.localeCompare(right, undefined, { numeric: true });
    });
    const lane = candidates[0]!;
    result.push(lane);
    remaining.delete(lane);
    for (const target of outgoing.get(lane)!.keys())
      unresolvedIncoming.get(target)!.delete(lane);
  }
  return { laneNodes, lanes: result };
}

function averageNeighborOrder(neighbors: Set<string>, order: Map<string, number>) {
  const values = [...neighbors].flatMap(key => order.has(key) ? [order.get(key)!] : []);
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
}

function reduceEdgeCrossings(
  columns: WorkbenchNode[][],
  incoming: Map<string, Set<string>>,
  outgoing: Map<string, Set<string>>,
  connectionCounts: Map<string, number>,
) {
  const order = new Map<string, number>();
  const refreshOrder = () => columns.forEach(column => column.forEach((node, index) => order.set(node.key, index)));
  const sortByNeighbors = (column: WorkbenchNode[], connections: Map<string, Set<string>>) => {
    if (column.every(node => workbenchLayoutFamily(node) === 'shot'))
      return;
    const previous = new Map(column.map((node, index) => [node.key, index]));
    column.sort((left, right) => {
      const leftScore = averageNeighborOrder(connections.get(left.key) ?? new Set(), order);
      const rightScore = averageNeighborOrder(connections.get(right.key) ?? new Set(), order);
      if (leftScore !== null && rightScore !== null && leftScore !== rightScore)
        return leftScore - rightScore;
      if (leftScore !== null && rightScore === null)
        return -1;
      if (leftScore === null && rightScore !== null)
        return 1;
      const leftConnections = connectionCounts.get(left.key) ?? 0;
      const rightConnections = connectionCounts.get(right.key) ?? 0;
      if (leftConnections !== rightConnections)
        return rightConnections - leftConnections;
      return previous.get(left.key)! - previous.get(right.key)!;
    });
  };

  refreshOrder();
  for (let sweep = 0; sweep < BARYCENTRIC_SWEEPS; sweep += 1) {
    for (let column = 1; column < columns.length; column += 1) {
      sortByNeighbors(columns[column]!, incoming);
      refreshOrder();
    }
    for (let column = columns.length - 2; column >= 0; column -= 1) {
      sortByNeighbors(columns[column]!, outgoing);
      refreshOrder();
    }
  }
}

/**
 * Rule-driven layered layout. Node families always receive distinct columns;
 * relationship affinity orders those columns, while measured dimensions and
 * neighbor barycenters prevent overlap and reduce edge crossings.
 */
export function buildWorkbenchAutoLayout(
  nodes: WorkbenchNode[],
  edges: WorkbenchEdge[] = [],
  options: WorkbenchAutoLayoutOptions = {},
): Record<string, Point> {
  if (!nodes.length)
    return {};
  const origin = options.origin ?? DEFAULT_ORIGIN;
  const columnGap = options.columnGap ?? DEFAULT_COLUMN_GAP;
  const rowGap = options.rowGap ?? DEFAULT_ROW_GAP;
  const maxColumnHeight = options.maxColumnHeight ?? Number.POSITIVE_INFINITY;
  const sizes = Object.fromEntries(nodes.map(node => [node.key, nodeSize(node, options.sizes ?? {})]));
  const positions: Record<string, Point> = {};
  const bandNodes = stableNodes(nodes).filter(node => workbenchLayoutBand(node) !== 'main');
  const mainNodes = nodes.filter(node => workbenchLayoutBand(node) === 'main');
  const bandNames = [...new Set(bandNodes.map(workbenchLayoutBand))];
  const headerBandNames = orderedHeaderBandNames(bandNames.filter(name => !name.startsWith('footer:')));
  const footerBandNames = bandNames.filter(name => name.startsWith('footer:'));
  let mainOriginY = origin.y;
  for (const bandName of headerBandNames) {
    const members = bandNodes.filter(node => workbenchLayoutBand(node) === bandName);
    let x = origin.x;
    let bandHeight = 0;
    for (const node of members) {
      positions[node.key] = { x, y: mainOriginY };
      x += sizes[node.key]!.width + columnGap;
      bandHeight = Math.max(bandHeight, sizes[node.key]!.height);
    }
    mainOriginY += bandHeight + rowGap;
  }
  if (!mainNodes.length) {
    let footerOriginY = mainOriginY;
    for (const bandName of footerBandNames) {
      const members = bandNodes.filter(node => workbenchLayoutBand(node) === bandName);
      let x = origin.x;
      let bandHeight = 0;
      for (const node of members) {
        positions[node.key] = { x, y: footerOriginY };
        x += sizes[node.key]!.width + columnGap;
        bandHeight = Math.max(bandHeight, sizes[node.key]!.height);
      }
      footerOriginY += bandHeight + rowGap;
    }
    preserveFixedPositions(nodes, positions, options.fixedNodeKeys);
    return positions;
  }

  const mainKeys = new Set(mainNodes.map(node => node.key));
  const mainEdges = edges.filter(edge => mainKeys.has(edge.source) && mainKeys.has(edge.target));
  const { outgoing, incoming } = graphConnections(mainNodes, mainEdges);
  const connectionCounts = graphConnectionCounts(mainNodes, mainEdges);
  const nodeByKey = new Map(mainNodes.map(node => [node.key, node]));
  const { laneNodes, lanes } = orderedLanes(mainNodes, mainEdges, options.relationshipRules ?? WORKBENCH_LAYOUT_RELATIONSHIP_RULES);
  const orderedColumns = lanes.map(lane => laneNodes.get(lane)!);
  enforcePinnedSequenceOrder(orderedColumns, nodeByKey, incoming, outgoing);
  reduceEdgeCrossings(orderedColumns, incoming, outgoing, connectionCounts);
  enforcePinnedSequenceOrder(orderedColumns, nodeByKey, incoming, outgoing);
  const columns = orderedColumns.flatMap((column) => {
    const family = workbenchLayoutFamily(column[0]!);
    return (family === 'shot' || family === 'result')
      ? packLane(column, sizes, rowGap, maxColumnHeight)
      : [column];
  });

  const columnWidths = columns.map(column => Math.max(...column.map(node => sizes[node.key]!.width)));
  const columnHeights = columns.map(column => (
    column.reduce((sum, node) => sum + sizes[node.key]!.height, 0)
    + Math.max(0, column.length - 1) * rowGap
  ));
  const layoutHeight = Math.max(...columnHeights);
  const columnX: number[] = [origin.x];
  for (let column = 1; column < columns.length; column += 1)
    columnX[column] = columnX[column - 1]! + columnWidths[column - 1]! + columnGap;

  columns.forEach((column, columnIndex) => {
    let y = mainOriginY + (layoutHeight - columnHeights[columnIndex]!) / 2;
    for (const node of column) {
      positions[node.key] = { x: columnX[columnIndex]!, y };
      y += sizes[node.key]!.height + rowGap;
    }
  });
  let footerOriginY = mainOriginY + layoutHeight + rowGap;
  for (const bandName of footerBandNames) {
    const members = bandNodes.filter(node => workbenchLayoutBand(node) === bandName);
    let x = origin.x;
    let bandHeight = 0;
    for (const node of members) {
      positions[node.key] = { x, y: footerOriginY };
      x += sizes[node.key]!.width + columnGap;
      bandHeight = Math.max(bandHeight, sizes[node.key]!.height);
    }
    footerOriginY += bandHeight + rowGap;
  }
  preserveFixedPositions(nodes, positions, options.fixedNodeKeys);
  return positions;
}
