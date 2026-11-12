import {useState} from 'react';
export function useOperation() {
  const [message,setMessage]=useState('');
  const [busy,setBusy]=useState(false);
  async function execute(action:()=>Promise<void>) {
    setBusy(true);setMessage('');
    try {await action();} catch(e) {setMessage((e as Error).message);} finally {setBusy(false);}
  }
  return {message,setMessage,busy,execute};
}
