import type {GetServerSideProps} from 'next';
import App from '../shop/App';
import {loadShopping} from '../server/shopping';
import type {ShoppingPage} from '../shop/page';

export const getServerSideProps:GetServerSideProps<ShoppingPage>=loadShopping;
export default App;
