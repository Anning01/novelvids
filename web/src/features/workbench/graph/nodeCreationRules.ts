import type { SupportedWorkbenchEdgeType, WorkbenchNode, WorkbenchNodeKind } from '../types/workbenchTypes';
import { classifyWorkbenchHandles, workbenchNodeHandles } from './handleCapabilities';

export interface WorkbenchNodeCreationCandidate {
  id: string;
  label: string;
  description: string;
  kind: WorkbenchNodeKind;
  data: WorkbenchNode['data'];
}

export interface WorkbenchConnectionOrigin {
  nodeId: string;
  handleId: string;
  handleType: 'source' | 'target';
}

export interface CompatibleNodeCreation {
  candidate: WorkbenchNodeCreationCandidate;
  candidateHandleId: string;
  edgeType: SupportedWorkbenchEdgeType;
}

function preferredHandleScore(required?: boolean, minConnections?: number, role?: string) {
  return (required ? 100 : 0) + (minConnections ?? 0) * 10 + (role === 'target' ? 2 : role === 'reference' ? 1 : 0);
}

export function compatibleNodeCreations(
  origin: WorkbenchConnectionOrigin,
  originNode: Pick<WorkbenchNode, 'kind' | 'data'>,
  candidates: WorkbenchNodeCreationCandidate[],
): CompatibleNodeCreation[] {
  return candidates.flatMap((candidate) => {
    const candidateNode = { kind: candidate.kind, data: candidate.data };
    const handles = workbenchNodeHandles(candidate.kind, candidate.data)[origin.handleType === 'source' ? 'target' : 'source'];
    const matches = handles.flatMap((handle) => {
      const edgeType = origin.handleType === 'source'
        ? classifyWorkbenchHandles(origin.handleId, handle.id, originNode, candidateNode)
        : classifyWorkbenchHandles(handle.id, origin.handleId, candidateNode, originNode);
      return edgeType ? [{ handle, edgeType }] : [];
    }).sort((left, right) => preferredHandleScore(right.handle.required, right.handle.minConnections, right.handle.role)
      - preferredHandleScore(left.handle.required, left.handle.minConnections, left.handle.role));
    const match = matches[0];
    return match
      ? [{ candidate, candidateHandleId: match.handle.id, edgeType: match.edgeType }]
      : [];
  });
}
