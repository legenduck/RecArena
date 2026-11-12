// The administrator credential is never shared with shopping requests.
export function adminClient(token:string) {
  async function request<T>(path:string, method='GET', body?:unknown):Promise<T> {
    const response=await fetch('/api/control/v1'+path,{method,headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},
      ...(body === undefined ? {} : {body:JSON.stringify(body)})});
    const result=await response.json();
    if (!response.ok) throw new Error(`${result.error?.message ?? 'Request failed'} (${result.error?.request_id ?? response.status})`);
    return result;
  }
  async function downloadExport(identifier:string) {
    const response=await fetch(`/api/control/v1/exports/${identifier}/download`,{headers:{Authorization:'Bearer '+token}});
    if (!response.ok) throw new Error('Export download failed.');
    const url=URL.createObjectURL(await response.blob());
    const link=document.createElement('a');link.href=url;link.download=`recarena-${identifier}.zip`;link.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  async function downloadAttachment(runId:string,attachmentId:string,name:string) {
    const response=await fetch(`/api/control/v1/runs/${runId}/attachments/${attachmentId}`,{headers:{Authorization:'Bearer '+token}});
    if (!response.ok) throw new Error('Attachment download failed.');
    const url=URL.createObjectURL(await response.blob());
    const link=document.createElement('a');link.href=url;link.download=name;link.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  return {request,downloadExport,downloadAttachment};
}
