import type {NextApiRequest,NextApiResponse} from 'next';
import {proxyShopping} from '../../../../server/proxy';
export const config={api:{bodyParser:false,responseLimit:false}};
export default function handler(req:NextApiRequest,res:NextApiResponse){return proxyShopping(req,res,'assets');}
