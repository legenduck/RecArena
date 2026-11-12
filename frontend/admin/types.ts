import type {PolicyConfig,Presentation} from '../generated/control';
export type Environment = {id:string; state:string; dataset_snapshot_id:string; review_snapshot_id:string; history_snapshot_id:string;
  presentation:Presentation; config:Partial<Presentation> & {policy?:{family:PolicyConfig['family']}; main_page_size?:number}};
export type Request=<T>(path:string,method?:string,body?:unknown)=>Promise<T>;
export type PreparedArtifact={manifest:{artifact_id:string;artifact_type:string;[key:string]:unknown};ready:boolean;registered:boolean};
export type EntrySettings={default_environment_id:string|null;policies:Record<string,string>;shop_url:string;admin_url:string};
